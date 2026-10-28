const $ = (selector) => document.querySelector(selector);
const connection = $("#connection");
const form = $("#case-form");
const fileInput = $("#screenshot");
const fileLabel = $("#file-label");
const message = $("#form-message");
const createButton = $("#create-button");
const runList = $("#run-list");
const detailPanel = $("#detail-panel");
const refreshButton = $("#refresh-button");
let selectedRunId = null;

const stageLabels = {
  intake: "Intake",
  reproduction: "Reproduction",
  "test-before": "Failing test",
  patch: "Patch",
  verification: "Verification",
  report: "Report",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

async function fileToDataUrl(file) {
  if (!file) return undefined;
  if (file.size > 10 * 1024 * 1024) throw new Error("Screenshot exceeds 10 MB.");
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function loadRuns({ selectNewest = false } = {}) {
  const { runs } = await api("/api/runs");
  if (!runs.length) {
    runList.innerHTML = '<div class="empty small">No evidence cases yet.</div>';
    return;
  }
  if (selectNewest || !selectedRunId || !runs.some((run) => run.id === selectedRunId)) selectedRunId = runs[0].id;
  runList.innerHTML = runs.map((run) => `
    <button class="run-card ${run.id === selectedRunId ? "selected" : ""}" data-run-id="${escapeHtml(run.id)}">
      <strong>${escapeHtml(run.title)}</strong>
      <small><span>${formatDate(run.updatedAt)}</span><span class="state ${escapeHtml(run.state)}">${escapeHtml(run.state)}</span></small>
    </button>`).join("");
  runList.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => selectRun(button.dataset.runId));
  });
  await renderRun(selectedRunId);
}

async function selectRun(runId) {
  selectedRunId = runId;
  runList.querySelectorAll("[data-run-id]").forEach((button) => button.classList.toggle("selected", button.dataset.runId === runId));
  await renderRun(runId);
}

function artifactUrl(run, artifact) {
  return `/runs/${encodeURIComponent(run.id)}/${artifact.path.split("/").map(encodeURIComponent).join("/")}`;
}

function isImage(artifact) {
  return /\.(png|jpe?g|webp|gif|svg)$/i.test(artifact.path);
}

async function renderRun(runId) {
  const { run } = await api(`/api/runs/${encodeURIComponent(runId)}`);
  const stages = Object.entries(run.stages).map(([name, stage]) => `
    <div class="stage-row">
      <span class="stage-dot ${escapeHtml(stage.status)}"></span>
      <div class="stage-name">${escapeHtml(stageLabels[name] || name)}</div>
      <div class="stage-copy">
        <strong>${escapeHtml(stage.status)}</strong>
        <p>${escapeHtml(stage.summary || "Waiting for evidence.")}</p>
        ${stage.command ? `<code>${escapeHtml(stage.command)}${stage.exitCode !== undefined ? ` · exit ${escapeHtml(stage.exitCode)}` : ""}</code>` : ""}
      </div>
    </div>`).join("");
  const images = run.artifacts.filter(isImage);
  const gallery = images.length ? `
    <h3 class="evidence-title">Visual evidence</h3>
    <div class="gallery">${images.map((artifact) => `
      <figure class="evidence-card">
        <img src="${artifactUrl(run, artifact)}" alt="${escapeHtml(artifact.label)}" />
        <figcaption><span>${escapeHtml(artifact.label)}</span><span>${escapeHtml(stageLabels[artifact.stage] || artifact.stage)}</span></figcaption>
      </figure>`).join("")}</div>` : "";
  detailPanel.innerHTML = `
    <div class="detail-header">
      <div><div class="kicker">Evidence case · ${escapeHtml(formatDate(run.createdAt))}</div><h2>${escapeHtml(run.title)}</h2><p>${escapeHtml(run.description)}</p></div>
      <div class="verdict ${escapeHtml(run.state)}">${run.state === "verified" ? "Verified fix" : escapeHtml(run.state)}</div>
    </div>
    <div class="timeline">${stages}</div>
    ${gallery}
    <div class="detail-actions">
      <button class="secondary" id="generate-report">Generate report</button>
      <a class="secondary" href="/reports/${encodeURIComponent(run.id)}" target="_blank" rel="noreferrer">Open report ↗</a>
    </div>`;
  $("#generate-report").addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    try {
      await api(`/api/runs/${encodeURIComponent(run.id)}/report`, { method: "POST" });
      await loadRuns();
    } finally {
      event.currentTarget.disabled = false;
    }
  });
}

fileInput.addEventListener("change", () => {
  fileLabel.textContent = fileInput.files[0]?.name || "Choose a screenshot";
});

const dropZone = $("#drop-zone");
for (const eventName of ["dragenter", "dragover"]) dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.remove("dragging"); });
dropZone.addEventListener("drop", (event) => {
  const [file] = event.dataTransfer.files;
  if (!file?.type.startsWith("image/")) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  fileLabel.textContent = file.name;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.className = "form-message";
  message.textContent = "Creating a durable evidence case…";
  createButton.disabled = true;
  try {
    const file = fileInput.files[0];
    const payload = {
      title: $("#title").value,
      description: $("#description").value,
      targetUrl: $("#target-url").value,
      screenshotDataUrl: await fileToDataUrl(file),
      screenshotName: file?.name,
    };
    const { run } = await api("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    selectedRunId = run.id;
    form.reset();
    fileLabel.textContent = "Choose a screenshot";
    message.className = "form-message success";
    message.textContent = `Case ${run.id} created. Continue in Codex with $reprosight.`;
    await loadRuns();
  } catch (error) {
    message.className = "form-message error";
    message.textContent = error.message;
  } finally {
    createButton.disabled = false;
  }
});

refreshButton.addEventListener("click", () => loadRuns());

async function boot() {
  try {
    await api("/api/health");
    connection.className = "connection online";
    connection.innerHTML = "<span></span> Local engine ready";
    await loadRuns();
  } catch (error) {
    connection.className = "connection offline";
    connection.innerHTML = "<span></span> Engine offline";
    message.className = "form-message error";
    message.textContent = error.message;
  }
}

boot();
