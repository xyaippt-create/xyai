import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const PROJECT_ROOT = path.dirname(fileURLToPath(import.meta.url));

function gitValue(args) {
  try {
    return execFileSync("git", args, {
      cwd: PROJECT_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}

function createBuildMetadata() {
  const productVersion = JSON.parse(readFileSync(path.join(PROJECT_ROOT, "product_version.json"), "utf8"));
  const builtAt = new Date().toISOString();
  const commit = (process.env.HDDE_BUILD_COMMIT || gitValue(["rev-parse", "--short=12", "HEAD"]) || "nogit")
    .trim()
    .slice(0, 12);
  const status = gitValue(["status", "--porcelain=v1", "--untracked-files=all"]);
  const worktree = status === null ? "unknown" : status ? "dirty" : "clean";
  const timestamp = builtAt.replace(/[-:.]/g, "");
  return {
    id: `${productVersion.display_version}+${commit}.${worktree}.${timestamp}`,
    builtAt,
  };
}

export default defineConfig(() => {
  const build = createBuildMetadata();
  const apiTarget = process.env.HDDE_API_TARGET || "http://127.0.0.1:8787";
  return {
    plugins: [react()],
    define: {
      __HDDE_BUILD_ID__: JSON.stringify(build.id),
      __HDDE_BUILD_TIME__: JSON.stringify(build.builtAt),
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": apiTarget,
      },
    },
  };
});
