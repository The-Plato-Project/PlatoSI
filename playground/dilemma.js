"use strict";

const $ = id => document.getElementById(id);
let bootstrap;
let current = null;
let runs = [];
let selectedRun = null;

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function text(parent, value) {
  parent.append(document.createTextNode(String(value)));
}

function renderValue(value, label = null) {
  if (value !== null && typeof value === "object") {
    const details = document.createElement("details");
    details.open = label === null;
    const summary = document.createElement("summary");
    const count = Array.isArray(value) ? `${value.length} item(s)` : `${Object.keys(value).length} field(s)`;
    summary.textContent = label === null ? count : `${label}: ${count}`;
    details.append(summary);
    const entries = Array.isArray(value) ? value.entries() : Object.entries(value);
    for (const [key, item] of entries) details.append(renderValue(item, key));
    return details;
  }
  const row = document.createElement("div");
  row.className = "structured-field";
  if (label !== null) {
    const name = document.createElement("strong");
    name.textContent = `${label}: `;
    row.append(name);
  }
  text(row, value === null ? "null" : value);
  return row;
}

function providerSummary(data) {
  const root = $("dilemma-provider");
  root.replaceChildren();
  const fields = {
    Installed: data.installed,
    Enabled: data.enabled,
    Available: data.available,
    "Provider version": data.provider && data.provider.version,
    "Dilemma package": data.provider && data.provider.package_version,
    "Artifact files": data.artifacts && data.artifacts.file_count,
    "Artifact bytes": data.artifacts && data.artifacts.total_bytes,
    "Artifact fingerprint": data.artifacts && data.artifacts.local_file_metadata_sha256,
    "Declared artifact revision": data.artifacts && data.artifacts.declared_revision,
    "Revision verified": data.artifacts && data.artifacts.revision_verified,
    "License status": data.provider && data.provider.license && data.provider.license.status
  };
  for (const [name, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null) root.append(renderValue(value, name));
  }
  if (data.error) root.append(renderValue(data.error, "Problem"));
}

function selectedFeature() {
  return bootstrap.features.find(item => item.id === $("dilemma-feature").value);
}

function populatePresets() {
  const feature = selectedFeature();
  $("dilemma-description").textContent = feature ? feature.description : "";
  const select = $("dilemma-preset");
  select.replaceChildren();
  for (const [index, preset] of (feature ? feature.presets : []).entries()) {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = preset.name;
    select.append(option);
  }
  applyPreset();
}

function applyPreset() {
  const feature = selectedFeature();
  const preset = feature && feature.presets[Number($("dilemma-preset").value)];
  $("dilemma-options").value = JSON.stringify(preset ? preset.options : {}, null, 2);
}

function setBusy(busy) {
  $("dilemma-run").disabled = busy || !bootstrap.available || !bootstrap.enabled;
  $("dilemma-stop").disabled = !busy;
  $("dilemma-feature").disabled = busy;
  $("dilemma-preset").disabled = busy;
}

function showRun(run) {
  selectedRun = run;
  $("dilemma-export").disabled = !run || run.status !== "complete";
  $("dilemma-structured").replaceChildren();
  $("dilemma-raw").textContent = "";
  if (!run) return;
  if (run.status === "complete") {
    $("dilemma-structured").append(renderValue(run.result));
    $("dilemma-raw").textContent = JSON.stringify(run.result, null, 2);
  } else {
    $("dilemma-structured").append(renderValue(run.error || run.status, "Status"));
  }
}

function renderHistory() {
  const root = $("dilemma-history");
  root.replaceChildren();
  for (const run of runs) {
    const row = document.createElement("label");
    row.className = "history-row";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.compareRun = run.localId;
    check.disabled = run.status !== "complete";
    check.addEventListener("change", compareRuns);
    const open = document.createElement("button");
    open.type = "button";
    open.textContent = `${run.feature} · ${run.status} · ${run.started}`;
    open.addEventListener("click", () => showRun(run));
    row.append(check, open);
    root.append(row);
  }
}

function compareRuns() {
  const ids = Array.from(document.querySelectorAll("[data-compare-run]:checked"), item => item.dataset.compareRun);
  if (ids.length > 2) {
    const last = document.querySelector(`[data-compare-run="${ids[2]}"]`);
    last.checked = false;
    ids.pop();
  }
  const root = $("dilemma-comparison");
  root.replaceChildren();
  if (ids.length !== 2) return;
  for (const id of ids) {
    const run = runs.find(item => item.localId === id);
    const section = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = `${run.feature} · ${run.started}`;
    const output = document.createElement("pre");
    output.textContent = JSON.stringify(run.result, null, 2);
    section.append(heading, output);
    root.append(section);
  }
}

async function poll(run) {
  try {
    const job = await request(`/api/jobs/${encodeURIComponent(run.jobId)}`);
    if (current !== run) return;
    if (job.status === "running") {
      setTimeout(() => poll(run), 300);
      return;
    }
    current = null;
    run.status = job.status;
    run.result = job.result;
    run.error = job.error;
    $("dilemma-run-status").textContent = job.status === "complete"
      ? `${run.feature} completed in ${job.result.output && job.result.output.seconds !== undefined ? job.result.output.seconds : "unknown"} second(s).`
      : `${run.feature}: ${job.error || job.status}`;
    setBusy(false);
    showRun(run);
    renderHistory();
  } catch (error) {
    if (current !== run) return;
    $("dilemma-run-status").textContent = `Connection problem: ${error.message}. Retrying…`;
    setTimeout(() => poll(run), 1000);
  }
}

$("dilemma-run").addEventListener("click", async () => {
  if (current) return;
  let options;
  try {
    options = JSON.parse($("dilemma-options").value);
    if (options === null || typeof options !== "object" || Array.isArray(options)) {
      throw new Error("Options must be a JSON object.");
    }
  } catch (error) {
    $("dilemma-run-status").textContent = `Invalid options: ${error.message}`;
    $("dilemma-options").focus();
    return;
  }
  const run = {
    localId: crypto.randomUUID(), feature: $("dilemma-feature").value,
    options, status: "starting", started: new Date().toLocaleString()
  };
  runs.unshift(run);
  runs = runs.slice(0, 30);
  current = run;
  setBusy(true);
  renderHistory();
  $("dilemma-run-status").textContent = `Running ${run.feature}…`;
  try {
    const job = await request("/api/dilemma/jobs", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({feature: run.feature, options})
    });
    run.jobId = job.id;
    run.status = "running";
    poll(run);
  } catch (error) {
    current = null;
    run.status = "error";
    run.error = error.message;
    setBusy(false);
    showRun(run);
    renderHistory();
    $("dilemma-run-status").textContent = `Error: ${error.message}`;
  }
});

$("dilemma-stop").addEventListener("click", async () => {
  if (!current || !current.jobId) return;
  try {
    await request(`/api/jobs/${encodeURIComponent(current.jobId)}/stop`, {method: "POST"});
    $("dilemma-run-status").textContent = "Cancellation requested. Some Dilemma operations cannot interrupt native work immediately.";
  } catch (error) {
    $("dilemma-run-status").textContent = `Could not cancel: ${error.message}`;
  }
});

$("dilemma-feature").addEventListener("change", populatePresets);
$("dilemma-preset").addEventListener("change", applyPreset);
$("dilemma-export").addEventListener("click", () => {
  if (!selectedRun || selectedRun.status !== "complete") return;
  const payload = {
    exported_at: new Date().toISOString(),
    feature: selectedRun.feature,
    options: selectedRun.options,
    response: selectedRun.result
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = `dilemma-${selectedRun.feature}-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  link.click();
  URL.revokeObjectURL(url);
});

async function initialize() {
  try {
    bootstrap = await request("/api/dilemma");
    providerSummary(bootstrap);
    $("dilemma-status").textContent = bootstrap.available && bootstrap.enabled
      ? `${bootstrap.features.length} evaluation features are ready.`
      : bootstrap.error || (bootstrap.enabled ? "Dilemma is unavailable." : "Dilemma is disabled.");
    for (const feature of bootstrap.features) {
      const option = document.createElement("option");
      option.value = feature.id;
      option.textContent = feature.title;
      $("dilemma-feature").append(option);
    }
    populatePresets();
    setBusy(false);
  } catch (error) {
    bootstrap = {available: false, enabled: false, features: []};
    $("dilemma-status").textContent = `Could not initialize: ${error.message}`;
    setBusy(false);
  }
}

initialize();
