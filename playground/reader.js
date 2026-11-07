"use strict";

const $ = id => document.getElementById(id);
let opened = null;
let selected = null;
let sequence = 0;
let currentJob = null;

async function request(path, payload) {
  const options = payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function node(tag, text, parent) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (parent) parent.append(element);
  return element;
}

function selection() {
  if (!$("override").checked) return [];
  return Array.from(document.querySelectorAll("#resources input:checked"), input => input.value);
}

function query() {
  const result = {corpus: opened && selected !== null ? opened.scope.provider : $("corpus").value,
          edition: opened && selected !== null ? opened.scope.edition
                   : ($("custom-reading").checked ? $("edition").value.trim() : $("work").value),
          scope: opened && selected !== null ? opened.scope.scope
                 : ($("custom-reading").checked ? $("custom-scope").value.trim() : $("scope").value),
          profile: $("profile").value,
          start: selected};
  if ($("override").checked) result.include = selection();
  return result;
}

function noteKey() {
  return `platosi-note:${JSON.stringify([opened.scope.provider, opened.scope.edition, opened.scope.scope, selected])}`;
}

function labelCitation(citation) {
  return citation.section || citation.page || "citation unavailable";
}

async function openReading() {
  const version = ++sequence;
  selected = null;
  opened = null;
  $("reading-text").replaceChildren();
  $("word-results").replaceChildren();
  $("notes-section").hidden = true;
  $("ai-section").hidden = true;
  $("reading-status").textContent = "Loading text…";
  try {
    const data = await request("/api/reader/scope", query());
    if (version !== sequence) return;
    opened = data;
    const chars = Array.from(data.scope.text);
    const fragment = document.createDocumentFragment();
    let cursor = 0;
    for (const token of data.tokens) {
      fragment.append(document.createTextNode(chars.slice(cursor, token.start).join("")));
      const button = node("button", token.form, fragment);
      button.type = "button";
      button.className = "greek-word";
      button.dataset.start = String(token.start);
      button.addEventListener("click", () => selectWord(token.start));
      cursor = token.end;
    }
    fragment.append(document.createTextNode(chars.slice(cursor).join("")));
    $("reading-text").replaceChildren(fragment);
    $("reading-status").textContent = $("custom-reading").checked
      ? `Reading the selected text and division. Select any word.`
      : `The Republic — Book ${data.scope.scope}. Select any word.`;
    $("word-status").textContent = "Select a word in the text.";
  } catch (error) {
    $("reading-status").textContent = `Could not open reading: ${error.message}`;
  }
}

async function selectWord(start) {
  if (!opened) return;
  selected = start;
  const version = ++sequence;
  for (const button of document.querySelectorAll(".greek-word.selected")) button.classList.remove("selected");
  const button = document.querySelector(`.greek-word[data-start="${start}"]`);
  if (button) button.classList.add("selected");
  $("word-status").textContent = `${button ? button.textContent : ""} — loading local evidence…`;
  $("word-results").replaceChildren();
  $("ai-results").replaceChildren();
  $("ai-status").textContent = "";
  currentJob = null;
  $("examine").disabled = false;
  $("ai-section").hidden = true;
  $("notes-section").hidden = false;
  try {
    $("notes").value = localStorage.getItem(noteKey()) || "";
    $("notes-status").textContent = "";
  } catch (error) {
    $("notes").value = "";
    $("notes-status").textContent = `Notes unavailable: ${error.message}`;
  }
  try {
    const result = await request("/api/reader/explore", query());
    if (version !== sequence) return;
    renderWord(result);
  } catch (error) {
    if (version === sequence) $("word-status").textContent = `Local lookup failed: ${error.message}`;
  }
}

function detail(parent, title, value) {
  const block = node("details", undefined, parent);
  node("summary", title, block);
  node("pre", typeof value === "string" ? value : JSON.stringify(value, null, 2), block);
}

function dictionaryExcerpts(xml) {
  const document = new DOMParser().parseFromString(xml, "application/xml");
  if (document.querySelector("parsererror")) throw new Error("The dictionary entry XML is invalid.");
  const senses = Array.from(document.getElementsByTagName("sense"));
  const entries = senses.length ? senses : [document.documentElement];
  return entries.map(sense => {
    const copy = sense.cloneNode(true);
    for (const nested of Array.from(copy.getElementsByTagName("sense"))) nested.remove();
    const text = copy.textContent.replace(/\s+/g, " ").trim();
    const chars = Array.from(text);
    return {
      label: sense.getAttribute("n") || "",
      text: chars.slice(0, 240).join("") + (chars.length > 240 ? "…" : ""),
      truncated: chars.length > 240
    };
  }).filter(sense => sense.text);
}

function renderDictionaryEntry(parent, entry) {
  const provider = entry.provider === "lsj-logeion" ? "LSJ / Logeion" : entry.provider;
  const item = node("section", undefined, parent);
  item.className = "dictionary-entry";
  node("h4", `${entry.headword || "Dictionary entry"} — ${provider}`, item);
  if (typeof entry.entry_xml === "string") {
    try {
      const senses = dictionaryExcerpts(entry.entry_xml);
      if (senses.length) {
        node("p", "Dictionary excerpts, in source order; not a choice of meaning in this passage.", item);
        const first = node("ul", undefined, item);
        for (const sense of senses.slice(0, 3)) {
          node("li", `${sense.label ? `${sense.label}: ` : ""}${sense.text}`, first);
        }
        if (senses.length > 3) {
          const more = node("details", undefined, item);
          node("summary", `More dictionary senses (${senses.length - 3})`, more);
          const list = node("ul", undefined, more);
          for (const sense of senses.slice(3)) {
            node("li", `${sense.label ? `${sense.label}: ` : ""}${sense.text}`, list);
          }
        }
      } else {
        node("p", "No readable sense was found in this entry; inspect the source record.", item);
      }
    } catch (error) {
      node("p", `Could not display dictionary excerpts: ${error.message}`, item).className = "warning";
    }
  } else {
    node("p", "This provider did not supply an XML entry for display; inspect its source record.", item);
  }
  detail(item, `Full source record (${entry.entry_id || entry.entry_ordinal || "entry"})`, entry);
}

function etymologyReferences(entry) {
  if (typeof entry.entry_xml !== "string") return [];
  const document = new DOMParser().parseFromString(entry.entry_xml, "application/xml");
  if (document.querySelector("parsererror")) throw new Error("The dictionary entry XML is invalid.");
  return Array.from(document.getElementsByTagName("etym"), element => {
    const parent = element.parentElement;
    const range = document.createRange();
    range.selectNodeContents(parent);
    range.setEndBefore(element);
    const before = range.toString();
    const content = element.textContent;
    const after = parent.textContent.slice(before.length + content.length);
    return (before.length > 100 ? "…" : "") + before.slice(-100)
      + content + after.slice(0, 100) + (after.length > 100 ? "…" : "");
  }).map(text => text.replace(/\s+/g, " ").trim()).filter(Boolean);
}

function renderWord(result) {
  $("word-status").textContent = `${result.word.form} — ${labelCitation(result.word.citation)}`;
  const panel = $("word-results");
  node("p", "Dictionary forms are possibilities, not final answers.", panel);
  detail(panel, "About these word forms", result.limitations);
  detail(panel, "Original passage and source", result.word);
  for (const warning of result.warnings) node("p", warning, panel).className = "warning";
  node("h3", "Definitions", panel);
  if (!result.analyses.length) node("p", "No possible dictionary forms were found.", panel);
  const grouped = new Map();
  const displayedEntries = new Set();
  for (const analysis of result.analyses) {
    if (!analysis.lemma) continue;
    if (!grouped.has(analysis.lemma)) grouped.set(analysis.lemma, []);
    grouped.get(analysis.lemma).push(analysis);
  }
  for (const [lemma, records] of grouped) {
    const item = node("div", undefined, panel);
    item.className = "candidate";
    let remembered = false;
    try { remembered = localStorage.getItem(`${noteKey()}:lemma`) === lemma; }
    catch (error) { $("notes-status").textContent = `Saved selection unavailable: ${error.message}`; }
    node("h4", lemma + (remembered ? " (your saved choice)" : ""), item);
    const button = node("button", "Find this word in the book", item);
    button.type = "button";
    button.addEventListener("click", () => findOccurrences(lemma, item));
    detail(item, `${records.length} analysis record(s) — ${records.map(r => r.provider).join(", ")}`, records);
    for (const entry of result.entries) {
      if (typeof entry.headword === "string" && entry.headword.normalize("NFC") === lemma.normalize("NFC")) {
        renderDictionaryEntry(item, entry);
        displayedEntries.add(entry);
      }
    }
  }
  const otherEntries = result.entries.filter(entry => !displayedEntries.has(entry));
  if (!result.entries.length || otherEntries.length) {
    node("h3", "Other matching dictionary entries", panel);
    if (!result.entries.length) node("p", "No selected dictionary returned an entry.", panel);
    for (const entry of otherEntries) renderDictionaryEntry(panel, entry);
  }
  node("h3", "Etymology", panel);
  let references = 0;
  for (const entry of result.entries) {
    try {
      for (const reference of etymologyReferences(entry)) {
        references++;
        const source = entry.provider === "lsj-logeion" ? "LSJ / Logeion" : entry.provider;
        node("p", `${entry.headword} — ${source}: ${reference}`, panel);
      }
    } catch (error) {
      node("p", `Could not read etymological references: ${error.message}`, panel).className = "warning";
    }
  }
  if (!references) node("p", "No etymological reference was found in the selected dictionary entries.", panel);
  else node("p", "These are dictionary references, not necessarily identified roots.", panel);
  node("h3", "Relationships", panel);
  node("p", "AI exploration of connections across a book or the whole work is not available yet.", panel);
  $("ai-section").hidden = !result.analyses.length;
}

async function findOccurrences(lemma, container) {
  const version = sequence;
  try {
    localStorage.setItem(`${noteKey()}:lemma`, lemma);
    $("notes-status").textContent = "Exploration choice saved on this device; it is not a verdict.";
  } catch (error) { $("notes-status").textContent = `Could not save exploration choice: ${error.message}`; }
  const previous = container.querySelector(".occurrences");
  if (previous) previous.remove();
  const output = node("div", undefined, container);
  output.className = "occurrences";
  output.textContent = "Finding source occurrences…";
  try {
    const data = await request("/api/reader/occurrences", {...query(), lemma});
    if (version !== sequence) return;
    output.replaceChildren();
    node("p", `${data.results.length} occurrence(s). ${data.limitations}`, output);
    for (const warning of data.warnings) node("p", warning, output).className = "warning";
    for (const item of data.results) {
      const button = node("button", `${item.form} — ${labelCitation(item.citation)}`, output);
      button.type = "button";
      button.addEventListener("click", async () => {
        const target = document.querySelector(`.greek-word[data-start="${item.start}"]`);
        if (target) { target.scrollIntoView({block: "center"}); target.focus(); }
        await selectWord(item.start);
      });
      detail(output, "Source passage and analyses", item);
    }
  } catch (error) {
    output.textContent = `Occurrence lookup failed: ${error.message}`;
  }
}

$("load").addEventListener("click", openReading);
$("save-notes").addEventListener("click", () => {
  if (!opened || selected === null) return;
  try {
    localStorage.setItem(noteKey(), $("notes").value);
    $("notes-status").textContent = "Saved on this device.";
  } catch (error) {
    $("notes-status").textContent = `Could not save notes: ${error.message}`;
  }
});
for (const id of ["profile", "override"]) {
  $(id).addEventListener("change", () => { if (selected !== null) selectWord(selected); });
}
$("resources").addEventListener("change", () => { if (selected !== null) selectWord(selected); });

$("discover").addEventListener("click", async () => {
  $("ai-status").textContent = "Looking for local models…";
  try {
    const data = await request("/api/bootstrap");
    for (const id of ["primary", "validation"]) {
      $(id).replaceChildren();
      const placeholder = node("option", "Select a model", $(id));
      placeholder.value = "";
      for (const provider of data.models) {
        for (const model of provider.models) {
          const option = node("option", `${model.name} (${provider.id})`, $(id));
          option.value = JSON.stringify({provider: provider.id, model: model.name});
        }
      }
    }
    $("ai-status").textContent = data.model_errors.join("; ") || "Select both models.";
  } catch (error) { $("ai-status").textContent = `Model discovery failed: ${error.message}`; }
});

async function poll(id, version) {
  try {
    const job = await request(`/api/jobs/${encodeURIComponent(id)}`);
    if (version !== sequence || currentJob !== id) return;
    if (job.status === "running") { setTimeout(() => poll(id, version), 1000); return; }
    currentJob = null;
    $("examine").disabled = false;
    if (job.status !== "complete") {
      $("ai-status").textContent = `Examination ${job.status}: ${job.error || ""}`;
      return;
    }
    const errors = ["primary", "validation"].filter(role => job.result[role].error);
    $("ai-status").textContent = errors.length
      ? `Examination incomplete: ${errors.map(role => `${role}: ${job.result[role].error}`).join("; ")}`
      : (job.result.cached ? "Cached examination." : "Examination complete.");
    $("ai-results").replaceChildren();
    node("p", job.result.warning, $("ai-results")).className = "warning";
    for (const role of ["primary", "validation"]) {
      const assessment = job.result[role];
      node("h3", role === "primary" ? "Primary assessment" : "Independent validation", $("ai-results"));
      if (assessment.error) node("p", assessment.error, $("ai-results")).className = "warning";
      for (const item of assessment.assessments || []) {
        node("p", `${item.lemma}: ${item.status} — ${item.reason} (${item.evidence_ids.join(", ") || "no evidence cited"})`, $("ai-results"));
      }
    }
    for (const item of job.result.comparison) {
      node("p", `${item.lemma}: ${item.comparison} (primary: ${item.primary}; validation: ${item.validation})`, $("ai-results"));
    }
    detail($("ai-results"), "Primary assessment", job.result.primary);
    detail($("ai-results"), "Independent validation assessment", job.result.validation);
    detail($("ai-results"), "Agreement and disagreement", job.result.comparison);
    detail($("ai-results"), "Evidence supplied to both models", job.result.evidence);
  } catch (error) {
    if (version === sequence) {
      currentJob = null;
      $("examine").disabled = false;
      $("ai-status").textContent = `Examination failed: ${error.message}`;
    }
  }
}

$("examine").addEventListener("click", async () => {
  if (!$("primary").value || !$("validation").value) {
    $("ai-status").textContent = "Select both models.";
    return;
  }
  const version = sequence;
  $("examine").disabled = true;
  $("ai-status").textContent = "Examining the evidence…";
  try {
    const job = await request("/api/reader/examine", {...query(),
      models: {primary: JSON.parse($("primary").value), validation: JSON.parse($("validation").value)},
      settings: {temperature: Number($("temperature").value), max_tokens: Number($("max-tokens").value)},
      fresh: $("fresh").checked});
    if (version !== sequence) { $("examine").disabled = false; return; }
    currentJob = job.id;
    poll(job.id, version);
  } catch (error) {
    $("examine").disabled = false;
    $("ai-status").textContent = `Could not start examination: ${error.message}`;
  }
});

async function initialize() {
  try {
    const data = await request("/api/reader/options");
    for (const name of data.profiles) {
      const option = node("option", name, $("profile"));
      option.value = name;
    }
    for (const resource of data.resources) {
      if (resource.type === "corpus" && resource.capabilities.includes("reading") && resource.enabled) {
        const option = node("option", resource.id, $("corpus"));
        option.value = resource.id;
      }
      if (["morphology", "dictionary"].includes(resource.type)) {
        const label = node("label", undefined, $("resources"));
        const input = node("input", undefined, label);
        input.type = "checkbox"; input.value = resource.id; input.disabled = !resource.enabled;
        label.append(document.createTextNode(`${resource.id}${resource.enabled ? "" : " (disabled)"}`));
      }
    }
    if ($("corpus").value) await openReading();
    else $("reading-status").textContent = "No enabled reading provider is installed.";
  } catch (error) { $("reading-status").textContent = `Could not initialize reader: ${error.message}`; }
}
initialize();
