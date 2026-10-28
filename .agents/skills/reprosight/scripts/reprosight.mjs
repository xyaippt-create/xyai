#!/usr/bin/env node
import process from "node:process";
import {
  createRun,
  doctor,
  generateReport,
  listRuns,
  readRun,
  recordStage,
} from "../runtime/src/core.mjs";
import { startReproSightServer } from "../runtime/src/server.mjs";

function parseArgs(tokens) {
  const args = { _: [] };
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token.startsWith("--")) {
      args._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = tokens[index + 1];
    if (next === undefined || next.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = next;
      index += 1;
    }
  }
  return args;
}

function print(value) {
  process.stdout.write(`${typeof value === "string" ? value : JSON.stringify(value, null, 2)}\n`);
}

function help() {
  print(`ReproSight — from bug screenshot to verified fix

Usage:
  reprosight init --repo <path> --title <text> --description <text> [--url <url>] [--screenshot <path>]
  reprosight record --repo <path> --run <id> --stage <stage> --status <status> [options]
  reprosight report --repo <path> --run <id>
  reprosight show --repo <path> --run <id>
  reprosight list --repo <path>
  reprosight serve --repo <path> [--port 4174]
  reprosight doctor --repo <path>

Record options:
  --summary <text> --command <text> --exit-code <number>
  --artifact <path> --artifact-label <text> --files <comma,separated,paths>`);
}

async function main() {
  const [command = "help", ...tokens] = process.argv.slice(2);
  const args = parseArgs(tokens);
  const repoPath = args.repo || process.cwd();

  if (command === "help" || command === "--help" || command === "-h") return help();
  if (command === "init") {
    const run = await createRun({
      repoPath,
      title: args.title,
      description: args.description,
      targetUrl: args.url,
      screenshotPath: args.screenshot,
    });
    return print({ id: run.id, runPath: `${run.repoRoot}\\.reprosight\\runs\\${run.id}`, state: run.state });
  }
  if (command === "record") {
    const run = await recordStage({
      repoPath,
      runId: args.run,
      stage: args.stage,
      status: args.status,
      summary: args.summary,
      command: args.command,
      exitCode: args["exit-code"],
      artifactPath: args.artifact,
      artifactLabel: args["artifact-label"],
      files: String(args.files || "").split(",").map((item) => item.trim()).filter(Boolean),
    });
    return print({ id: run.id, state: run.state, stage: args.stage, status: run.stages[args.stage].status });
  }
  if (command === "report") {
    const result = await generateReport(repoPath, args.run);
    return print({ id: result.run.id, verdict: result.run.state, html: result.htmlPath, markdown: result.markdownPath });
  }
  if (command === "show") return print(await readRun(repoPath, args.run));
  if (command === "list") {
    return print((await listRuns(repoPath)).map((run) => ({ id: run.id, title: run.title, state: run.state })));
  }
  if (command === "doctor") return print(await doctor(repoPath));
  if (command === "serve") {
    const { port } = await startReproSightServer({ repoPath, port: args.port });
    print(`ReproSight dashboard: http://127.0.0.1:${port}`);
    return;
  }
  throw new Error(`Unknown command: ${command}`);
}

main().catch((error) => {
  process.stderr.write(`ReproSight error: ${error.message}\n`);
  process.exitCode = 1;
});
