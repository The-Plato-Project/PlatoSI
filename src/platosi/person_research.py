"""Online-cached, model-grounded research for dialogue-specific proper names."""

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import unicodedata
from contextlib import closing
from urllib.parse import urlencode
from urllib.request import Request, urlopen


VERSION = 1
MAX_SOURCE_EXCERPT = 3000
GREEK_TERM = re.compile(r"^[\u0370-\u03ff\u1f00-\u1fff\u0300-\u036f]+$")

ROOT_SCHEMA = {
    "type": "object",
    "properties": {
        "roots": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
    },
    "required": ["roots"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "person": {"type": "string"},
        "name_meaning": {"type": "string"},
        "relationships": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
    },
    "required": ["person", "name_meaning", "relationships"],
    "additionalProperties": False,
}


class PersonResearchCache:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute(
            "CREATE TABLE IF NOT EXISTS web_cache ("
            "url TEXT PRIMARY KEY, response_json TEXT NOT NULL, fetched_at TEXT NOT NULL "
            "DEFAULT CURRENT_TIMESTAMP)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS model_cache ("
            "cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL, created_at TEXT NOT NULL "
            "DEFAULT CURRENT_TIMESTAMP)"
        )
        return db

    def web(self, url, fetch):
        with self.lock, closing(self._connect()) as db:
            row = db.execute(
                "SELECT response_json, fetched_at FROM web_cache WHERE url = ?", (url,)
            ).fetchone()
            if row is not None:
                return json.loads(row[0]), True, row[1]
        value = fetch(url)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self.lock, closing(self._connect()) as db:
            db.execute(
                "INSERT OR REPLACE INTO web_cache(url,response_json) VALUES (?,?)",
                (url, encoded),
            )
            db.commit()
        return value, False, None

    def model(self, cache_key, generate):
        with self.lock, closing(self._connect()) as db:
            row = db.execute(
                "SELECT response_json FROM model_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
            if row is not None:
                return json.loads(row[0]), True
        value = generate()
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self.lock, closing(self._connect()) as db:
            db.execute(
                "INSERT OR REPLACE INTO model_cache(cache_key,response_json) VALUES (?,?)",
                (cache_key, encoded),
            )
            db.commit()
        return value, False


class PersonResearch:
    def __init__(self, root: Path, fetch_json=None):
        self.root = Path(root)
        self.cache = PersonResearchCache(
            self.root / "data" / "person-research-cache-v1.sqlite"
        )
        self.fetch_json = fetch_json or self._fetch_json

    @staticmethod
    def _fetch_json(url):
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "PlatoSI/1.0 local scholarly reader",
            },
        )
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"Research source returned HTTP {response.status}")
            if response.headers.get_content_type() != "application/json":
                raise ValueError("Research source returned non-JSON content")
            value = json.loads(response.read(2_000_001).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Research source returned a non-object response")
            return value

    def _cached_json(self, url):
        return self.cache.web(url, self.fetch_json)

    @staticmethod
    def _source(source_id, kind, title, url, excerpt, provider, cached):
        return {
            "id": source_id,
            "kind": kind,
            "title": title,
            "url": url,
            "excerpt": excerpt.strip()[:MAX_SOURCE_EXCERPT],
            "provider": provider,
            "cached": cached,
        }

    def online_sources(self, lemma):
        sources = []
        warnings = []
        wikidata_url = "https://www.wikidata.org/w/api.php?" + urlencode({
            "action": "wbsearchentities",
            "search": lemma,
            "language": "en",
            "format": "json",
            "limit": 5,
            "origin": "*",
        })
        try:
            result, cached, _ = self._cached_json(wikidata_url)
            for item in result.get("search", []):
                if not isinstance(item, dict):
                    continue
                entity_id = item.get("id")
                label = item.get("label")
                description = item.get("description", "")
                if not isinstance(entity_id, str) or not isinstance(label, str):
                    continue
                sources.append(self._source(
                    f"S{len(sources) + 1}",
                    "person_authority",
                    label,
                    f"https://www.wikidata.org/wiki/{entity_id}",
                    description if isinstance(description, str) else "",
                    "Wikidata",
                    cached,
                ))
        except (OSError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            warnings.append(f"Wikidata lookup failed: {type(error).__name__}: {error}")

        wikipedia_url = "https://en.wikipedia.org/w/api.php?" + urlencode({
            "action": "query",
            "generator": "search",
            "gsrsearch": lemma,
            "gsrlimit": 5,
            "prop": "extracts|info",
            "inprop": "url",
            "exintro": 1,
            "explaintext": 1,
            "format": "json",
            "formatversion": 2,
        })
        try:
            result, cached, _ = self._cached_json(wikipedia_url)
            pages = result.get("query", {}).get("pages", [])
            pages = pages if isinstance(pages, list) else []
            pages.sort(key=lambda item: item.get("index", 999) if isinstance(item, dict) else 999)
            for item in pages:
                if not isinstance(item, dict):
                    continue
                title, url, extract = item.get("title"), item.get("fullurl"), item.get("extract")
                if not all(isinstance(value, str) for value in (title, url, extract)):
                    continue
                sources.append(self._source(
                    f"S{len(sources) + 1}",
                    "biographical_reference",
                    title,
                    url,
                    extract,
                    "Wikipedia",
                    cached,
                ))
        except (OSError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            warnings.append(f"Wikipedia lookup failed: {type(error).__name__}: {error}")

        wiktionary_url = "https://en.wiktionary.org/w/api.php?" + urlencode({
            "action": "query",
            "titles": lemma,
            "prop": "extracts|info",
            "inprop": "url",
            "explaintext": 1,
            "format": "json",
            "formatversion": 2,
        })
        try:
            result, cached, _ = self._cached_json(wiktionary_url)
            pages = result.get("query", {}).get("pages", [])
            for item in pages if isinstance(pages, list) else []:
                if not isinstance(item, dict) or item.get("missing"):
                    continue
                title, url, extract = item.get("title"), item.get("fullurl"), item.get("extract")
                if not all(isinstance(value, str) for value in (title, url, extract)):
                    continue
                sources.append(self._source(
                    f"S{len(sources) + 1}",
                    "name_reference",
                    title,
                    url,
                    extract,
                    "Wiktionary",
                    cached,
                ))
        except (OSError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            warnings.append(f"Wiktionary lookup failed: {type(error).__name__}: {error}")
        return sources, warnings

    @staticmethod
    def _model_json(model_call, prompt, schema):
        last_error = None
        for attempt in range(2):
            retry = "" if attempt == 0 else "\nYour prior response was invalid. Return only the required JSON object."
            response = model_call(prompt + retry, schema)
            if not isinstance(response, dict) or not isinstance(response.get("text"), str):
                last_error = ValueError("Model provider returned an invalid response")
                continue
            try:
                value = json.loads(response["text"])
            except json.JSONDecodeError as error:
                last_error = ValueError("Model provider returned invalid JSON")
                continue
            if not isinstance(value, dict):
                last_error = ValueError("Model provider returned a non-object JSON response")
                continue
            return value, {key: item for key, item in response.items() if key != "text"}
        raise last_error

    @staticmethod
    def _bare(value):
        return "".join(
            character for character in unicodedata.normalize("NFD", value).casefold()
            if not unicodedata.category(character).startswith("M")
        )

    @classmethod
    def _name_candidates(cls, lemma):
        bare = cls._bare(lemma)
        candidates = []
        if bare.endswith("ων") and len(bare) > 4:
            candidates.append(bare[:-2] + "ος")
        return candidates

    @classmethod
    def _shares_name_stem(cls, lemma, candidate):
        name = cls._bare(lemma)
        root = cls._bare(candidate)
        common = 0
        for left, right in zip(name, root):
            if left != right:
                break
            common += 1
        return common >= 4 and common >= min(len(name), len(root)) - 2

    def root_sources(self, lemma, context, model_call, dictionary_lookup):
        prompt = (
            "Return JSON only. Propose at most three Ancient Greek lexical headwords that may "
            "help investigate the formation or meaning of this personal name. These are search "
            "candidates, not established etymologies. Every candidate must share the name's "
            "orthographic stem; do not use words merely found near the name. Do not explain them.\n"
            f"NAME: {json.dumps(lemma, ensure_ascii=False)}"
        )
        key = self._cache_key("roots-v2", lemma)

        def generate():
            value, model = self._model_json(model_call, prompt, ROOT_SCHEMA)
            return {"value": value, "model": model}

        cached_result, hit = self.cache.model(key, generate)
        proposed = cached_result.get("value", {}).get("roots", [])
        if not isinstance(proposed, list):
            raise ValueError("Model root response is invalid")
        sources = []
        accepted = []
        candidates = [*self._name_candidates(lemma), *proposed]
        for root in candidates:
            if (not isinstance(root, str) or not root or len(root) > 100
                    or GREEK_TERM.fullmatch(root) is None
                    or not self._shares_name_stem(lemma, root)):
                continue
            records = dictionary_lookup(root)
            if not records:
                continue
            for record in records[:1]:
                headword = record.get("headword", root)
                if not isinstance(headword, str) or headword in accepted:
                    continue
                accepted.append(headword)
                source = record.get("source", {})
                repository = source.get("repository")
                revision = source.get("revision")
                if not isinstance(repository, str):
                    continue
                url = repository.rstrip("/")
                if isinstance(revision, str) and revision:
                    url += f"/tree/{revision}"
                xml = record.get("entry_xml")
                sources.append(self._source(
                    "",
                    "lexical_root_candidate",
                    f"LSJ: {headword}",
                    url,
                    " ".join(
                        part.strip()
                        for part in re.sub(r"<[^>]+>", " ", xml or "").split()
                        if part.strip()
                    ),
                    "LSJ",
                    False,
                ))
            if accepted:
                break
        return accepted, sources, cached_result.get("model", {}), hit

    def summarize(self, lemma, context, roots, sources, model_call, model_identity):
        evidence = [{key: value for key, value in source.items() if key != "cached"}
                    for source in sources]
        prompt = (
            "Return JSON only. You are assisting a reader of Plato. Use only the supplied "
            "evidence. Every factual sentence must cite one or more source IDs in square "
            "brackets, such as [S1]. Every relationships array item must include its own source "
            "citation. Distinguish similarly named people and say when identity "
            "is uncertain. A lexical-root candidate proposed by the model is only a possible "
            "comparison unless an online source explicitly establishes the etymology; explicitly "
            "say when that connection is not established. Do not "
            "use outside knowledge. Keep person and name_meaning under 120 words each.\n"
            f"NAME: {json.dumps(lemma, ensure_ascii=False)}\n"
            f"VALIDATED LEXICAL COMPARISON CANDIDATES: {json.dumps(roots, ensure_ascii=False)}\n"
            f"SOURCES: {json.dumps(evidence, ensure_ascii=False)}"
        )
        valid = {source["id"] for source in sources}
        source_by_id = {source["id"]: source for source in sources}
        name_reference_text = self._bare(" ".join(
            source["excerpt"] for source in sources if source["kind"] == "name_reference"
        ))
        unsupported_etymology = bool(
            roots and self._bare(roots[0]) not in name_reference_text
        )

        def sanitize_citations(value):
            removed = 0
            sanitized = {}
            for field in ("person", "name_meaning"):
                retained = []
                sentences = re.split(
                    r"(?<=\])\s+|(?<=[.!?])\s+(?!\[S[0-9]+\])",
                    value.get(field, "").strip(),
                )
                for sentence in sentences:
                    citations = set(re.findall(r"\[(S[0-9]+)\]", sentence))
                    if sentence and citations and citations <= valid:
                        retained.append(sentence)
                    elif sentence:
                        removed += 1
                sanitized[field] = " ".join(retained)
            relationships = []
            for relationship in value.get("relationships", []):
                citations = set(re.findall(r"\[(S[0-9]+)\]", relationship))
                nonlexical = any(
                    source_by_id[source_id]["kind"] != "lexical_root_candidate"
                    for source_id in citations if source_id in source_by_id
                )
                compares_unsupported_root = (
                    unsupported_etymology
                    and self._bare(roots[0]) in self._bare(relationship)
                )
                if (relationship and citations and citations <= valid and nonlexical
                        and not compares_unsupported_root):
                    relationships.append(relationship)
                elif relationship:
                    removed += 1
            sanitized["relationships"] = relationships
            if unsupported_etymology:
                lexical = next(
                    (source for source in sources
                     if source["kind"] == "lexical_root_candidate"),
                    None,
                )
                if lexical is not None:
                    prefix = (
                        f"Possible lexical comparison, not an established name etymology: "
                        f"{roots[0]}. [{lexical['id']}]"
                    )
                    sanitized["name_meaning"] = prefix
            return sanitized, removed

        key = self._cache_key("summary-v6", lemma, context, roots, evidence, model_identity)

        def generate():
            value, model = self._model_json(model_call, prompt, SUMMARY_SCHEMA)
            value, removed = sanitize_citations(value)
            return {"value": value, "model": model, "removed_claims": removed}

        cached_result, hit = self.cache.model(key, generate)
        value = cached_result.get("value")
        if not isinstance(value, dict):
            raise ValueError("Cached model summary is invalid")
        cited = set(re.findall(r"\[(S[0-9]+)\]", json.dumps(value, ensure_ascii=False)))
        warnings = []
        removed = cached_result.get("removed_claims", 0)
        if isinstance(removed, int) and removed > 0:
            warnings.append(f"Discarded {removed} model claim(s) without valid source citations.")
        if sources and not cited:
            warnings.append("The model summary did not cite any retrieved sources.")
        return value, cached_result.get("model", {}), hit, warnings

    @staticmethod
    def _cache_key(*parts):
        encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def research(self, lemma, context, model_call, model_identity, dictionary_lookup):
        sources, warnings = self.online_sources(lemma)
        roots = []
        root_model = {}
        root_cache_hit = False
        try:
            roots, lexical_sources, root_model, root_cache_hit = self.root_sources(
                lemma, context, model_call, dictionary_lookup
            )
            sources.extend(lexical_sources)
        except (ValueError, RuntimeError, OSError, TimeoutError) as error:
            warnings.append(f"Name-root analysis failed: {type(error).__name__}: {error}")
        for index, source in enumerate(sources, 1):
            source["id"] = f"S{index}"
        summary = None
        summary_model = {}
        summary_cache_hit = False
        if sources:
            try:
                summary, summary_model, summary_cache_hit, model_warnings = self.summarize(
                    lemma, context, roots, sources, model_call, model_identity
                )
                warnings.extend(model_warnings)
            except (ValueError, RuntimeError, OSError, TimeoutError) as error:
                warnings.append(f"Person summary failed: {type(error).__name__}: {error}")
        return {
            "contract": "platosi.person-research.v1",
            "status": "ok" if summary is not None else "partial",
            "lemma": lemma,
            "roots": roots,
            "summary": summary,
            "sources": sources,
            "model": summary_model or root_model or model_identity,
            "cache": {
                "root_model_hit": root_cache_hit,
                "summary_model_hit": summary_cache_hit,
                "all_sources_hit": bool(sources) and all(source["cached"] for source in sources
                                                         if source["kind"] != "lexical_root_candidate"),
            },
            "warnings": warnings,
        }
