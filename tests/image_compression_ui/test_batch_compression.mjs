import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { batchItemOutcome } from "../../src/batchCompression.js";

const sha = (value) => String(value).padStart(64, "0");
const intake = (index) => ({
  source_token: `token-${index}`, source_sha256: sha(index), size_bytes: 100,
  display_name: "sample.png", format: "PNG", width: 64, height: 64,
  has_alpha: false, safe_preview_url: `/preview/${index}`, expires_at: 9999999999,
});
function outcome(index, keep = false) {
  const scheme = keep ? "keep_original" : "png_lossless";
  const winner = {
    scheme_id: scheme, source_selected: keep, quality_gate: { status: "PASS" },
    file_size: 40, output_path: `/output/${index}.png`, status: "AVAILABLE", selected: true, identity_status: "VALID",
  };
  return {
    task: { task_id: `task-${index}`, result_id: keep ? "" : `result-${index}` },
    result: {
      task_id: `task-${index}`, source_sha256: sha(index), source_size_bytes: 100,
      winner_scheme_id: scheme, winner, candidates: keep ? [] : [winner],
      public_output_count: keep ? 0 : 1, output_created: !keep,
      output_size_bytes: 40, output_path: `/output/${index}.png`, output_sha256: sha(index + 100), delivery_eligible: !keep,
    },
  };
}

// A05 single-result guards remain frozen. Durable queue behavior is covered by A06 tests.
test("public cards use the registered Result hash, without inventing a card SHA field", () => {
  const data = outcome(0);
  assert.equal(data.result.winner.output_sha256, undefined);
  assert.equal(batchItemOutcome(data, intake(0)).outputSha256, data.result.output_sha256);
  data.result.winner.file_size += 1;
  assert.throws(() => batchItemOutcome(data, intake(0)), /唯一压缩结果/);
  data.result.winner.file_size -= 1;
  data.result.winner.identity_status = "RESULT_IDENTITY_MISMATCH";
  assert.throws(() => batchItemOutcome(data, intake(0)), /唯一压缩结果/);
});

test("KEEP_ORIGINAL cannot be accepted with a fake Result or output", () => {
  for (const tamper of [
    (data) => { data.task.result_id = "fake-result"; },
    (data) => { data.result.public_output_count = 1; },
    (data) => { data.result.output_created = true; },
  ]) {
    const data = outcome(1, true); tamper(data);
    assert.throws(() => batchItemOutcome(data, intake(1)));
  }
});

test("unsafe winner, extra output, wrong task or SHA cannot be displayed as completed", () => {
  for (const tamper of [
    (data) => { data.result.winner.quality_gate.status = "FAIL"; },
    (data) => { data.result.public_output_count = 2; },
    (data) => { data.result.candidates.push({}); },
    (data) => { data.task.task_id = "other-task"; },
    (data) => { data.result.output_sha256 = "invalid-sha"; },
    (data) => { data.result.source_sha256 = sha(555); },
    (data) => { data.result.output_size_bytes = 101; },
  ]) {
    const data = outcome(0); tamper(data);
    assert.throws(() => batchItemOutcome(data, intake(0)));
  }
});

test("batch panel is inside compression with multiple input and accessible progress, not a primary route", () => {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  const page = read("../../src/CompressionPage.jsx");
  const panel = read("../../src/BatchCompressionPanel.jsx");
  assert.match(page, /<BatchCompressionPanel onNavigate=\{onNavigate\}/);
  assert.match(panel, /type="file" multiple/);
  assert.match(panel, /aria-live="polite"/);
  assert.match(page, /compressionBatch.getSnapshot\(\).batchId/);
  for (const action of ["pause", "resume", "cancel"]) assert.ok(panel.includes(`batch-compression-${action}`));
  assert.doesNotMatch(panel, /beforeunload/);
  assert.match(panel, /<progress max=\{summary.total \|\| 1\} value=\{finished\}/);
  assert.doesNotMatch(read("../../src/appRoutes.js"), /batch-compression/);
});

test("batch page keeps the mode switch and gives completion, selection and state UI real semantics", () => {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  const panel = read("../../src/BatchCompressionPanel.jsx");
  const styles = read("../../src/BatchCompressionPanel.css");

  assert.match(panel, /hdde-batch-compression-summary__header[\s\S]*批量交付（\{selectedItems\.length\}）[\s\S]*进入输出中心/);
  assert.match(panel, /aria-label="全选当前可交付项"/);
  assert.match(panel, /BatchThumbnail[\s\S]*item\.sourcePreviewUrl/);
  assert.match(panel, /isPaused && summary\.waiting > 0[\s\S]*batch-compression-resume/);
  assert.match(panel, /!isPreparing && !isRestoring && control === "RUNNING"[\s\S]*batch-compression-pause/);
  assert.match(panel, /正在准备 \$\{preparedCount\}\/\$\{summary\.total\}/);
  assert.match(panel, /正在压缩 \$\{activeOrdinal\}\/\$\{summary\.total\}/);
  assert.match(panel, /hdde-batch-compression-summary__relation/);
  assert.match(panel, /outputItem\.delivery_failure_reason[\s\S]*outputItem\.delivery_failure_code/);
  assert.match(
    styles,
    /\.hdde-compression-page > \.hdde-page-header \.hdde-compression-mode-tabs\s*\{[\s\S]*?gap:\s*0;[\s\S]*?border:\s*1px solid var\(--border-color\);/,
  );
  assert.match(styles, /\.hdde-batch-thumbnail\s*\{[\s\S]*?width:\s*56px;[\s\S]*?height:\s*56px;/);
  assert.match(styles, /tr\[data-status="PROCESSING"\][\s\S]*var\(--brand-primary-soft\)/);
  assert.match(styles, /@media \(max-width: 860px\)/);
});

test("batch source thumbnails and same-level action groups use state-independent stable UI contracts", () => {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  const panel = read("../../src/BatchCompressionPanel.jsx");
  const styles = read("../../src/BatchCompressionPanel.css");

  assert.match(panel, /BatchThumbnail[\s\S]*item\.sourcePreviewUrl/);
  assert.doesNotMatch(panel, /function BatchThumbnail\(\{ item, outputItem/);
  assert.match(styles, /\.hdde-batch-compression-summary__actions\s*\{[\s\S]*?align-items:\s*center;[\s\S]*?gap:\s*12px;/);
  assert.match(styles, /\.hdde-batch-compression-summary__actions button\s*\{[\s\S]*?height:\s*48px;[\s\S]*?margin:\s*0;/);
  assert.match(styles, /\.hdde-batch-delivery-dialog \.hdde-batch-compression-actions button\s*\{[\s\S]*?height:\s*44px;[\s\S]*?margin:\s*0;/);
});

test("batch list and completion use the established processing-page card rhythm", () => {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  const panel = read("../../src/BatchCompressionPanel.jsx");
  const styles = read("../../src/BatchCompressionPanel.css");

  assert.doesNotMatch(panel, /className="hdde-batch-compression hdde-page-stack"/);
  assert.match(panel, /className="hdde-batch-compression-list-card hdde-processing-panel"/);
  assert.match(panel, /<HddeSectionHeader[\s\S]*?headingId="batch-compression-list-title"/);
  assert.match(panel, /className="hdde-batch-compression-summary hdde-processing-panel"/);
  assert.match(styles, /\.hdde-batch-compression\s*\{[\s\S]*?gap:\s*14px;/);
  assert.match(styles, /\.hdde-batch-compression-list-card\s*\{[\s\S]*?gap:\s*16px;[\s\S]*?padding:\s*18px;/);
});
