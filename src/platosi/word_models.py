"""Optional, independently prompted model examinations of local evidence."""

import hashlib
import json
import math
from contextlib import closing
from pathlib import Path
import sqlite3

from platosi.cancellation import Cancelled
from platosi.inquiry import model_provider


INSTRUCTIONS = """Examine only the supplied Ancient Greek and attributed evidence.
Candidate analyses are provisional; do not invent citations, entries, forms, or grammatical evidence.
Do not offer literary, philosophical, or symbolic interpretation. Preserve uncertainty.
Return only a JSON object with an assessments array. For each supplied candidate lemma include:
{"lemma":"exact candidate", "status":"plausible|unlikely|uncertain",
 "reason":"short explanation distinguishing evidence from hypothesis", "evidence_ids":["E1"]}.
Use only supplied evidence IDs. If evidence is insufficient, mark uncertain."""


def evidence_package(result):
    evidence = [{"id": "E1", "record": result["word"]}]
    for analysis in result["analyses"]:
        evidence.append({"id": f"E{len(evidence) + 1}", "record": analysis})
    for entry in result["entries"]:
        record = dict(entry)
        if len(record.get("entry_xml", "")) > 8000:
            record["entry_xml"] = record["entry_xml"][:8000]
            record["entry_xml_truncated"] = True
        evidence.append({"id": f"E{len(evidence) + 1}", "record": record})
    package = {"evidence": evidence, "limitations": result["limitations"]}
    encoded = json.dumps(package, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > 100_000:
        raise ValueError("Selected evidence exceeds the examination limit; select fewer resources.")
    return package


def parse_assessment(text, package):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("assessments"), list):
        raise ValueError("Expected a JSON object with an assessments array")
    valid_ids = {item["id"] for item in package["evidence"]}
    lemmas = {item["record"]["lemma"] for item in package["evidence"]
              if item["record"].get("evidence_type") == "candidate_analysis"
              and isinstance(item["record"].get("lemma"), str)}
    seen = set()
    for item in data["assessments"]:
        if not isinstance(item, dict):
            raise ValueError("Assessment must be an object")
        lemma, status, reason, refs = (item.get("lemma"), item.get("status"),
                                       item.get("reason"), item.get("evidence_ids"))
        if (not isinstance(lemma, str) or lemma not in lemmas or lemma in seen
                or status not in ("plausible", "unlikely", "uncertain")
                or not isinstance(reason, str) or not reason.strip()
                or not isinstance(refs, list) or (status != "uncertain" and not refs)
                or any(not isinstance(ref, str) or ref not in valid_ids for ref in refs)):
            raise ValueError("Assessment contains an invalid candidate, status, reason, or evidence ID")
        seen.add(lemma)
    if seen != lemmas:
        raise ValueError("Assessment does not cover every supplied candidate")
    return data["assessments"]


def compare(primary, validation):
    first = {item["lemma"]: item["status"] for item in primary}
    second = {item["lemma"]: item["status"] for item in validation}
    return [{"lemma": lemma, "primary": first.get(lemma, "not assessed"),
             "validation": second.get(lemma, "not assessed"),
             "comparison": ("not comparable" if lemma not in first or lemma not in second
                            else "agreement" if first[lemma] == second[lemma] else "disagreement")}
            for lemma in sorted(set(first) | set(second))]


def assessment_schema(package):
    lemmas = list(dict.fromkeys(item["record"]["lemma"] for item in package["evidence"]
                               if item["record"].get("evidence_type") == "candidate_analysis"
                               and isinstance(item["record"].get("lemma"), str)))
    ids = [item["id"] for item in package["evidence"]]
    return {"type": "object", "additionalProperties": False, "required": ["assessments"],
            "properties": {"assessments": {
                "type": "array", "minItems": len(lemmas), "maxItems": len(lemmas),
                "items": {"type": "object", "additionalProperties": False,
                          "required": ["lemma", "status", "reason", "evidence_ids"],
                          "properties": {
                              "lemma": {"type": "string", "enum": lemmas},
                              "status": {"type": "string", "enum": ["plausible", "unlikely", "uncertain"]},
                              "reason": {"type": "string"},
                              "evidence_ids": {"type": "array", "items": {"type": "string", "enum": ids}}
                          }}}}}


class Examination:
    def __init__(self, root):
        self.path = Path(root) / "data" / "word-exploration-cache.sqlite"

    def _cache(self, key, value=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS examinations (key TEXT PRIMARY KEY, result TEXT NOT NULL)")
            if value is not None:
                db.execute("INSERT OR REPLACE INTO examinations VALUES (?, ?)",
                           (key, json.dumps(value, ensure_ascii=False)))
                return None
            row = db.execute("SELECT result FROM examinations WHERE key = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def run(self, registry, local, choices, settings, fresh, cancellation):
        if not isinstance(choices, dict) or set(choices) != {"primary", "validation"}:
            raise ValueError("Select primary and validation models")
        if not isinstance(fresh, bool):
            raise ValueError("Fresh examination must be true or false")
        if not isinstance(settings, dict):
            raise ValueError("Examination settings must be an object")
        temperature = settings.get("temperature")
        maximum = settings.get("max_tokens")
        if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
                or not math.isfinite(temperature) or not 0 <= temperature <= 2
                or isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 8192):
            raise ValueError("Invalid examination generation settings")
        package = evidence_package(local)
        if not local["analyses"]:
            raise ValueError("No candidate analyses are available to examine")
        options = {"generation": {"temperature": temperature}, "max_tokens": maximum,
                   "response_format": "json", "response_schema": assessment_schema(package)}
        messages = [{"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": "Evidence:\n" + json.dumps(package, ensure_ascii=False)
                     + "\nExamine each candidate in the passage. Return only the requested JSON assessment."}]
        loaded, failures, identities = {}, {}, {}
        for role in ("primary", "validation"):
            choice = choices[role]
            if (not isinstance(choice, dict) or not isinstance(choice.get("provider"), str)
                    or not isinstance(choice.get("model"), str) or not choice["provider"] or not choice["model"]):
                raise ValueError(f"Select a provider and model for {role}")
            try:
                registration, provider = model_provider(registry, choice["provider"], "chat")
                models = provider.list_models()
                model = next((item for item in models if item.get("name") == choice["model"]), None)
                if model is None:
                    raise ValueError(f"Model {choice['model']!r} is unavailable")
                identities[role] = {"provider": registration.manifest["id"],
                                    "provider_version": registration.manifest["version"],
                                    "config_digest": hashlib.sha256(json.dumps(
                                        registration.manifest["config"], sort_keys=True).encode("utf-8")).hexdigest(),
                                    "model": choice["model"], "digest": model.get("digest")}
                loaded[role] = provider
            except (OSError, RuntimeError, ValueError, ImportError) as error:
                failures[role] = str(error)
        cacheable = len(loaded) == 2 and all(identities[r].get("digest") for r in loaded)
        cache_key = hashlib.sha256(json.dumps(
            {"messages": messages, "identities": identities, "options": options},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if cacheable and not fresh:
            cached = self._cache(cache_key)
            if cached is not None:
                return {**cached, "cached": True}
        results = {}
        for role in ("primary", "validation"):
            if role in failures:
                results[role] = {"error": failures[role], "model": choices[role]}
                continue
            try:
                cancellation.check()
                response = loaded[role].chat(messages, {**options, "model": choices[role]["model"]}, cancellation)
                if not isinstance(response, dict) or not isinstance(response.get("text"), str):
                    raise ValueError("Model returned an invalid response")
                text = response["text"]
                try:
                    if response.get("done_reason") == "length":
                        raise ValueError("Model response was truncated at the token limit")
                    assessments = parse_assessment(text, package)
                    results[role] = {"model": identities[role], "assessments": assessments, "raw": text}
                except (ValueError, json.JSONDecodeError) as error:
                    results[role] = {"model": identities[role], "raw": text,
                                     "error": f"Invalid structured model assessment: {error}"}
            except Cancelled:
                raise
            except (OSError, RuntimeError, ValueError, ImportError) as error:
                results[role] = {"model": identities[role], "error": str(error)}
        comparison = compare(results["primary"].get("assessments", []),
                             results["validation"].get("assessments", []))
        same_model = (len(identities) == 2 and
                      identities["primary"]["provider"] == identities["validation"]["provider"] and
                      identities["primary"]["model"] == identities["validation"]["model"])
        result = {"evidence": package, "primary": results["primary"], "validation": results["validation"],
                  "comparison": comparison, "cached": False,
                  "warning": ("Model output is unverified. Agreement does not establish certainty."
                              + (" Both assessments use the same model." if same_model else ""))}
        if cacheable and all("error" not in results[r] for r in results):
            self._cache(cache_key, result)
        return result
