"use strict";

const $ = id => document.getElementById(id);
let defaults;
let history = [];
let current = null;
let conversation = 0;
let stopPending = false;

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setBusy(busy) {
  $("send").disabled = busy || !$("model").value;
  $("stop").disabled = !busy;
  $("status").textContent = busy ? "Generating locally…" : "Ready";
}

function appendMessage(role, text) {
  const box = document.createElement("article");
  box.className = `message ${role}`;
  const title = document.createElement("h3");
  title.textContent = role === "user" ? "You" : "Model";
  const body = document.createElement("div");
  body.className = "content";
  for (const part of text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g)) {
    let node;
    if (part.startsWith("**") && part.endsWith("**")) {
      node = document.createElement("strong");
      node.textContent = part.slice(2, -2);
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 1) {
      node = document.createElement("em");
      node.textContent = part.slice(1, -1);
    } else if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      node = document.createElement("code");
      node.textContent = part.slice(1, -1);
    } else {
      node = document.createTextNode(part);
    }
    body.append(node);
  }
  box.append(title, body);
  $("messages").append(box);
  $("messages").scrollTop = $("messages").scrollHeight;
  return box;
}

function addEvidence(box, result) {
  if (result.model) {
    const model = document.createElement("p");
    model.textContent = `Model: ${result.model.provider} / ${result.model.model || ""}`;
    box.append(model);
  }
  if (result.evidence && result.evidence.length) {
    const container = document.createElement("div");
    container.className = "evidence";
    for (const item of result.evidence) {
      const record = item.record;
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      const section = record.stephanus_at_match && record.stephanus_at_match.section;
      summary.textContent = `[${item.id}] ${record.evidence_type || "source"} — ${record.provider || "unknown provider"}${section ? `, ${section}` : ""}`;
      const content = document.createElement("pre");
      content.textContent = JSON.stringify(record, null, 2);
      details.append(summary, content);
      container.append(details);
    }
    box.append(container);
  }
  for (const text of result.warnings || []) {
    const warning = document.createElement("p");
    warning.className = "warning";
    warning.textContent = text;
    box.append(warning);
  }
}

function resourceSelection() {
  if (!$("override").checked) return [];
  return Array.from(document.querySelectorAll("#resources input:checked"), input => input.value);
}

async function poll(id, version) {
  try {
    const job = await request(`/api/jobs/${encodeURIComponent(id)}`);
    if (version !== conversation || current !== id) return;
    if (job.status === "running") {
      setTimeout(() => poll(id, version), 400);
      return;
    }
    current = null;
    setBusy(false);
    if (job.status === "complete") {
      if (job.result.answer) {
        history.push({role: "assistant", content: job.result.answer});
        addEvidence(appendMessage("assistant", job.result.answer), job.result);
      } else {
        addEvidence(appendMessage("assistant", "No response was generated."), job.result);
      }
    } else {
      $("status").textContent = job.status === "cancelled" ? "Generation stopped." : `Error: ${job.error}`;
    }
  } catch (error) {
    if (version !== conversation) return;
    $("status").textContent = `Connection problem: ${error.message}. Retrying…`;
    setTimeout(() => poll(id, version), 1500);
  }
}

$("form").addEventListener("submit", async event => {
  event.preventDefault();
  const text = $("message").value.trim();
  if (!text || current) return;
  const selected = $("model").selectedOptions[0];
  if (!selected) return;
  const include = resourceSelection();
  if ($("mode").value === "grounded" && $("override").checked && !include.length) {
    $("status").textContent = "Select at least one resource, including a corpus provider.";
    return;
  }
  const version = conversation;
  stopPending = false;
  current = "starting";
  history.push({role: "user", content: text});
  const userMessage = appendMessage("user", text);
  $("message").value = "";
  setBusy(true);
  try {
    const payload = {
      provider: selected.dataset.provider, model: selected.dataset.model,
      system_prompt: $("system-prompt").value, temperature: Number($("temperature").value),
      max_tokens: Number($("max-tokens").value),
      mode: $("mode").value, messages: history, profile: $("profile").value,
      include, text: $("text").value.trim(), edition: $("edition").value.trim(),
      citation: $("citation").value.trim(), headword: $("headword").value.trim(),
      form: $("morph-form").value.trim()
    };
    const job = await request("/api/jobs", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
    });
    if (version !== conversation) {
      await request(`/api/jobs/${encodeURIComponent(job.id)}/stop`, {method: "POST"});
      return;
    }
    current = job.id;
    if (stopPending) {
      await request(`/api/jobs/${encodeURIComponent(job.id)}/stop`, {method: "POST"});
    }
    poll(current, version);
  } catch (error) {
    if (version !== conversation) return;
    current = null;
    history.pop();
    userMessage.remove();
    $("message").value = text;
    setBusy(false);
    $("status").textContent = `Error: ${error.message}`;
  }
});

$("stop").addEventListener("click", async () => {
  if (!current) return;
  if (current === "starting") {
    stopPending = true;
    $("status").textContent = "Stopping…";
    return;
  }
  try {
    await request(`/api/jobs/${encodeURIComponent(current)}/stop`, {method: "POST"});
  } catch (error) {
    $("status").textContent = `Could not stop generation: ${error.message}`;
  }
});

$("new").addEventListener("click", async () => {
  const old = current;
  conversation++;
  current = null;
  history = [];
  $("messages").replaceChildren();
  $("message").value = "";
  setBusy(false);
  if (old && old !== "starting") {
    try { await request(`/api/jobs/${encodeURIComponent(old)}/stop`, {method: "POST"}); }
    catch (error) { $("status").textContent = `Could not stop previous generation: ${error.message}`; }
  }
});

$("mode").addEventListener("change", () => {
  const grounded = $("mode").value === "grounded";
  $("grounded").hidden = !grounded;
  $("mode-description").textContent = grounded
    ? "Uses selected text and scholarly resources, with source attribution."
    : "Direct conversation. No scholarly retrieval is invoked.";
});
$("temperature").addEventListener("input", () => $("temperature-value").textContent = $("temperature").value);
$("reset-prompt").addEventListener("click", () => $("system-prompt").value = defaults.default_prompt);

async function initialize() {
  try {
    defaults = await request("/api/bootstrap");
    $("system-prompt").value = defaults.default_prompt;
    $("grounding-prompt").textContent = defaults.grounding_instructions;
    for (const provider of defaults.models) {
      for (const model of provider.models) {
        const option = document.createElement("option");
        option.value = `${provider.id}:${model.name}`;
        option.dataset.provider = provider.id;
        option.dataset.model = model.name;
        option.textContent = `${model.name} (${provider.id})`;
        $("model").append(option);
      }
    }
    for (const name of defaults.profiles) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      $("profile").append(option);
    }
    for (const resource of defaults.resources) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = resource.id;
      input.disabled = !resource.enabled;
      label.append(input, document.createTextNode(`${resource.id} (${resource.type}${resource.enabled ? "" : ", disabled"})`));
      $("resources").append(label);
    }
    setBusy(false);
    if (!$("model").value) $("status").textContent = `No local chat models available. ${defaults.model_errors.join("; ")}`;
    else if (defaults.model_errors.length) $("status").textContent = defaults.model_errors.join("; ");
  } catch (error) {
    $("send").disabled = true;
    $("status").textContent = `Could not load settings: ${error.message}`;
  }
}
initialize();
