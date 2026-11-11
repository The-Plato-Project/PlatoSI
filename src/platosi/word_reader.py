"""Text-anchored local word exploration using reader-selected providers."""

import unicodedata
import sqlite3
import threading
from pathlib import Path

from platosi.profiles import Profiles, select
from platosi.registry import Registry
from platosi.unicode_search import key


def tokens(text):
    start = None
    for i, char in enumerate(text):
        category = unicodedata.category(char)
        greek = "GREEK" in unicodedata.name(char, "") and category.startswith("L")
        if greek or (start is not None and category.startswith("M")):
            if start is None:
                start = i
        elif start is not None:
            yield {"start": start, "end": i, "form": text[start:i]}
            start = None
    if start is not None:
        yield {"start": start, "end": len(text), "form": text[start:]}


def citation_at(scope, offset):
    result = dict(scope["initial_citation"])
    for marker in scope["milestones"]:
        if marker["offset"] > offset:
            break
        result[marker["unit"]] = marker["n"]
    return result


def occurrence(scope, token, analyses):
    start, end = token["start"], token["end"]
    left, right = max(0, start - 100), min(len(scope["text"]), end + 100)
    editorial = [m for m in scope["source_markup"] if m["start"] < end and m["end"] > start]
    return {
        "evidence_type": "editorial_text" if editorial else "primary_text",
        "provider": scope["provider"], "provider_version": scope["provider_version"],
        "source": scope["source"], "license": scope["license"], "source_path": scope["source_path"],
        "edition": scope["edition"], "scope": scope["scope"], "form": token["form"],
        "start": start, "end": end, "citation": citation_at(scope, start),
        "context": scope["text"][left:right], "context_match_start": start - left,
        "context_match_end": end - left, "source_markup": editorial, "analyses": analyses,
    }


class WordReader:
    def __init__(self, root):
        self.root = Path(root)
        self.registry = None
        self.fingerprint = None
        self.lock = threading.Lock()

    def _registry(self):
        paths = sorted((self.root / "plugins").glob("*/plugin.json"))
        config = self.root / "data" / "plugin-config.json"
        if config.exists():
            paths.append(config)
        fingerprint = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        with self.lock:
            if self.registry is None or fingerprint != self.fingerprint:
                self.registry = Registry(self.root)
                self.fingerprint = fingerprint
            return self.registry

    def scope(self, provider_id, edition, scope):
        registry = self._registry()
        registration = registry.providers.get(provider_id)
        if not registration or not registration.enabled or "reading" not in registration.manifest["capabilities"]:
            raise ValueError(f"Reading provider {provider_id!r} is missing, disabled, or unsupported")
        provider = registration.load()
        if not provider.available():
            raise ValueError(f"Reading provider {provider_id!r} is unavailable")
        records = provider.reading(edition, scope)
        if len(records) != 1:
            raise ValueError("The requested reading scope was not found or is ambiguous")
        return records[0]

    def _profile(self, name):
        return Profiles(self.root).get(name) if name else None

    def _select(self, registry, capability, profile, payload):
        if "include" in payload and payload["include"] == []:
            return [], []
        return select(registry, capability, profile, payload.get("include"), tolerate_errors=True)

    def explore(self, payload):
        scope = self.scope(payload["corpus"], payload["edition"], payload["scope"])
        start = payload["start"]
        if isinstance(start, bool) or not isinstance(start, int):
            raise ValueError("Word position must be an integer")
        token = next((t for t in tokens(scope["text"]) if t["start"] == start), None)
        if token is None:
            raise ValueError("Selected position is not a Greek word in this reading scope")
        profile = self._profile(payload.get("profile"))
        registry = self._registry()
        selection, active = self._select(registry, "analyze", profile, payload)
        analyses, warnings = [], []
        for registration, provider in active:
            try:
                found = provider.analyze(token["form"], "exact", 1000)
                analyses.extend(found)
                if len(found) >= 1000:
                    warnings.append(f"{registration.manifest['id']}: candidate results may be truncated.")
            except (OSError, RuntimeError, ValueError, ImportError, sqlite3.Error) as error:
                warnings.append(f"{registration.manifest['id']}: analysis failed: {error}")
        dictionaries, dict_active = self._select(registry, "lookup", profile, payload)
        lemmas = list(dict.fromkeys([a["lemma"] for a in analyses if a.get("lemma")]))
        queries = list(dict.fromkeys([token["form"], *lemmas]))
        entries = []
        for registration, provider in dict_active:
            for query in queries:
                try:
                    found = provider.lookup(query, "exact", 1000)
                    entries.extend(found)
                    if len(found) >= 1000:
                        warnings.append(f"{registration.manifest['id']}: dictionary results for {query} may be truncated.")
                except (OSError, RuntimeError, ValueError, ImportError, sqlite3.Error) as error:
                    warnings.append(f"{registration.manifest['id']}: lookup failed for {query}: {error}")
        for entry in selection + dictionaries:
            if entry["reason"] in ("not installed", "source or current index unavailable") or (
                    entry["reason"] and entry["reason"].startswith("provider error:")):
                message = f"{entry['id']}: {entry['reason']}"
                if message not in warnings:
                    warnings.append(message)
        return {"word": occurrence(scope, token, []), "analyses": analyses,
                "entries": entries, "selections": {"analyze": selection, "lookup": dictionaries},
                "warnings": warnings,
                "limitations": "Candidates may be incomplete, generated, or incorrect; no analysis is authoritative."}

    def occurrences(self, payload):
        lemma = payload.get("lemma")
        if not isinstance(lemma, str) or not lemma.strip():
            raise ValueError("Select a nonempty candidate lemma")
        scope = self.scope(payload["corpus"], payload["edition"], payload["scope"])
        all_tokens = list(tokens(scope["text"]))
        forms = list(dict.fromkeys(key(t["form"]) for t in all_tokens))
        selection, active = self._select(self._registry(), "match_forms",
                                         self._profile(payload.get("profile")), payload)
        by_form = {}
        warnings = [f"{entry['id']}: {entry['reason']}" for entry in selection
                    if entry["reason"] in ("not installed", "source or current index unavailable")
                    or (entry["reason"] and entry["reason"].startswith("provider error:"))]
        for registration, provider in active:
            try:
                records = provider.match_forms(lemma, forms)
                if any(key(record["lemma"]) != key(lemma) for record in records):
                    raise ValueError("provider returned a different lemma")
                for record in records:
                    by_form.setdefault(key(record["form"]), []).append(record)
            except (OSError, RuntimeError, ValueError, ImportError, sqlite3.Error) as error:
                warnings.append(f"{registration.manifest['id']}: occurrence lookup failed: {error}")
        results = [occurrence(scope, token, by_form[key(token["form"])])
                   for token in all_tokens if key(token["form"]) in by_form]
        return {"lemma": lemma, "results": results, "selections": selection, "warnings": warnings,
                "limitations": ("Direct provider mappings for exact surface forms only; "
                                "results may be incomplete and do not establish contextual correctness. "
                                "Related roots and compounds are not merged.")}
