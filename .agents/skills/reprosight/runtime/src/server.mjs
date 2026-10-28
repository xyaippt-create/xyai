import { createServer as createHttpServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  contentTypeFor,
  createRun,
  ensureInside,
  generateReport,
  getRunPath,
  listRuns,
  readRun,
  recordStage,
  resolveRepository,
} from "./core.mjs";

const DEFAULT_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../web");

function sendJson(response, status, value) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  response.end(body);
}

function sendError(response, status, error) {
  sendJson(response, status, { error: error instanceof Error ? error.message : String(error) });
}

async function readJsonBody(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > 12 * 1024 * 1024) throw new Error("Request body exceeds 12 MB.");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function sendFile(response, filePath) {
  const info = await stat(filePath).catch(() => null);
  if (!info?.isFile()) return false;
  const body = await readFile(filePath);
  response.writeHead(200, {
    "content-type": contentTypeFor(filePath),
    "content-length": body.length,
    "cache-control": "no-store",
  });
  response.end(body);
  return true;
}

function summarizeRun(run) {
  return {
    id: run.id,
    title: run.title,
    description: run.description,
    state: run.state,
    createdAt: run.createdAt,
    updatedAt: run.updatedAt,
    targetUrl: run.targetUrl,
    verification: run.stages.verification.status,
  };
}

export async function createReproSightServer({ repoPath = process.cwd(), webRoot = DEFAULT_WEB_ROOT } = {}) {
  const repoRoot = await resolveRepository(repoPath);
  const resolvedWebRoot = path.resolve(webRoot);

  return createHttpServer(async (request, response) => {
    try {
      const requestUrl = new URL(request.url || "/", "http://localhost");
      const pathname = decodeURIComponent(requestUrl.pathname);

      if (request.method === "GET" && pathname === "/api/health") {
        return sendJson(response, 200, { ok: true, repoRoot });
      }
      if (request.method === "GET" && pathname === "/api/runs") {
        const runs = await listRuns(repoRoot);
        return sendJson(response, 200, { runs: runs.map(summarizeRun) });
      }
      if (request.method === "POST" && pathname === "/api/runs") {
        const body = await readJsonBody(request);
        const run = await createRun({
          repoPath: repoRoot,
          title: body.title,
          description: body.description,
          targetUrl: body.targetUrl,
          screenshotDataUrl: body.screenshotDataUrl,
          screenshotName: body.screenshotName,
        });
        return sendJson(response, 201, { run });
      }

      const runMatch = /^\/api\/runs\/([^/]+)$/.exec(pathname);
      if (request.method === "GET" && runMatch) {
        return sendJson(response, 200, { run: await readRun(repoRoot, runMatch[1]) });
      }

      const stageMatch = /^\/api\/runs\/([^/]+)\/stages$/.exec(pathname);
      if (request.method === "POST" && stageMatch) {
        const body = await readJsonBody(request);
        const run = await recordStage({ repoPath: repoRoot, runId: stageMatch[1], ...body });
        return sendJson(response, 200, { run });
      }

      const reportApiMatch = /^\/api\/runs\/([^/]+)\/report$/.exec(pathname);
      if (request.method === "POST" && reportApiMatch) {
        const result = await generateReport(repoRoot, reportApiMatch[1]);
        return sendJson(response, 200, { run: result.run, url: `/reports/${result.run.id}` });
      }

      const reportMatch = /^\/reports\/([^/]+)$/.exec(pathname);
      if (request.method === "GET" && reportMatch) {
        const runPath = getRunPath(repoRoot, reportMatch[1]);
        let reportPath = path.join(runPath, "report.html");
        if (!(await stat(reportPath).catch(() => null))) {
          reportPath = (await generateReport(repoRoot, reportMatch[1])).htmlPath;
        }
        if (await sendFile(response, reportPath)) return;
      }

      const artifactMatch = /^\/runs\/([^/]+)\/(.+)$/.exec(pathname);
      if (request.method === "GET" && artifactMatch) {
        const runPath = getRunPath(repoRoot, artifactMatch[1]);
        const artifactPath = ensureInside(runPath, path.join(runPath, artifactMatch[2]));
        if (await sendFile(response, artifactPath)) return;
        return sendError(response, 404, "Artifact not found.");
      }

      if (request.method === "GET") {
        const requested = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
        const staticPath = ensureInside(resolvedWebRoot, path.join(resolvedWebRoot, requested));
        if (await sendFile(response, staticPath)) return;
        if (await sendFile(response, path.join(resolvedWebRoot, "index.html"))) return;
      }

      return sendError(response, 404, "Not found.");
    } catch (error) {
      const clientError = /required|invalid|unknown|not found|does not exist|exceeds|screenshot/i.test(error.message);
      return sendError(response, clientError ? 400 : 500, error);
    }
  });
}

export async function startReproSightServer(options = {}) {
  const server = await createReproSightServer(options);
  const requestedPort = Number(options.port ?? 4174);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(requestedPort, options.host || "127.0.0.1", resolve);
  });
  const address = server.address();
  return { server, port: typeof address === "object" ? address.port : requestedPort };
}
