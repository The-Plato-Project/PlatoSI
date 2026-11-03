"use strict";

const $ = id => document.getElementById(id);
const republic = "urn:cts:greekLit:tlg0059.tlg030.perseus-grc2";
let sequence = 0;

function add(parent, tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  parent.append(element);
  return element;
}

async function request(path, body) {
  const options = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  };
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function showWarnings(parent, section) {
  if (section.status === "unavailable") add(parent, "p", "This information is not currently available.", "warning");
  if (section.warnings.length) {
    const details = add(parent, "details");
    add(details, "summary", "Availability and source details");
    for (const warning of section.warnings) add(details, "p", warning, "warning");
  }
  if (section.status !== "unavailable" && !section.records.length) add(parent, "p", "No matches found.");
}

function source(parent, record) {
  const details = add(parent, "details");
  add(details, "summary", "Source and attribution");
  const metadata = {source: record.source, license: record.license, provider: record.provider,
                    edition: record.edition, citations: record.citations, limitations: record.limitations};
  add(details, "pre", JSON.stringify(metadata, null, 2));
}

function showWord(result) {
  const output = $("results");
  add(output, "h3", "Possible analyses");
  add(output, "p", result.limitations);
  showWarnings(output, result.analyses);
  for (const analysis of result.analyses.records) {
    const item = add(output, "article", undefined, "lookup-item");
    add(item, "h4", analysis.lemma || "Candidate analysis");
    if (analysis.tag) add(item, "p", `Form: ${analysis.tag}`);
    source(item, analysis);
  }
  add(output, "h3", "Dictionary entries");
  showWarnings(output, result.entries);
  for (const entry of result.entries.records) {
    const item = add(output, "article", undefined, "lookup-item");
    add(item, "h4", entry.headword || "Dictionary entry");
    if (typeof entry.entry_xml === "string") {
      const xml = new DOMParser().parseFromString(entry.entry_xml, "application/xml");
      if (xml.querySelector("parsererror")) {
        add(item, "p", "This dictionary entry could not be displayed.", "warning");
      } else {
        const text = xml.documentElement.textContent.replace(/\s+/g, " ").trim();
        const excerpt = Array.from(text);
        add(item, "p", excerpt.slice(0, 600).join("") + (excerpt.length > 600 ? "…" : ""));
        if (excerpt.length > 600) {
          const details = add(item, "details");
          add(details, "summary", "Full dictionary entry");
          add(details, "p", text);
        }
      }
    } else {
      add(item, "p", "This source did not supply a readable entry.", "warning");
    }
    source(item, entry);
  }
}

function showPassages(result, requestedPassage) {
  const output = $("results");
  showWarnings(output, result);
  for (const record of result.records) {
    const item = add(output, "article", undefined, "lookup-item");
    const citation = record.stephanus_at_match && record.stephanus_at_match.section;
    add(item, "h3", citation ? (requestedPassage ? citation : `Match at ${citation}`) : "Source passage");
    if (record.edition) add(item, "p", record.edition, "lookup-edition");
    if (!requestedPassage) add(item, "p", "Surrounding source text; the citation identifies the match.");
    const text = requestedPassage ? record.match : record.text;
    if (typeof text === "string") {
      add(item, "p", text, "lookup-greek");
    } else {
      add(item, "p", "The requested source text is unavailable.", "warning");
    }
    source(item, record);
  }
}

async function lookup(title, operation, payload, render) {
  const version = ++sequence;
  $("result-title").textContent = title;
  $("result-status").textContent = "Looking up…";
  $("results").replaceChildren();
  try {
    const result = await request("/api/lookup", {operation, payload});
    if (version !== sequence) return;
    $("result-status").textContent = "Results are source evidence, not a final reading.";
    render(result);
  } catch (error) {
    if (version === sequence) $("result-status").textContent = `Lookup failed: ${error.message}`;
  }
}

$("word-form").addEventListener("submit", event => {
  event.preventDefault();
  const form = $("word").value.trim();
  if (form) lookup(`Exploring ${form}`, "word.analyze", {form}, showWord);
});

$("search-form").addEventListener("submit", event => {
  event.preventDefault();
  const text = $("search").value.trim();
  if (text) lookup(`Finding ${text}`, "text.search", {text}, result => showPassages(result, false));
});

$("passage-form").addEventListener("submit", event => {
  event.preventDefault();
  const citation = $("citation").value.trim();
  if (citation) lookup(`Republic ${citation}`, "text.passage", {edition: republic, citation},
                       result => showPassages(result, true));
});

async function initialize() {
  try {
    const result = await request("/api/lookups");
    const missing = result.capabilities.filter(item => !item.available).map(item => item.title);
    const word = result.capabilities.find(item => item.operation === "word.analyze");
    const morphology = word.parts.find(item => item.capability === "analyze");
    if (!morphology.available) missing.push("Possible word forms");
    $("availability").textContent = missing.length
      ? `Not currently available: ${missing.join(", ")}. Other lookups remain available.`
      : "Word, text, and passage lookups are available.";
  } catch (error) {
    $("availability").textContent = `Could not check available lookups: ${error.message}`;
  }
}

initialize();
