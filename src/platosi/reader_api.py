"""Reader-facing lookups shared by the playground and local integration API."""

import hashlib
import json
import sqlite3
import threading
import unicodedata
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path

from platosi import __version__
from platosi.cancellation import Cancellation
from platosi.canonical_text import CONTRACT, CanonicalCorpus, INVENTORY, LocationError
from platosi.dialogue_lexicon import DialogueLexiconIndex
from platosi.dialogue_morphology import DialogueMorphologyIndex
from platosi.inquiry import inquire, model_provider
from platosi.person_research import PersonResearch
from platosi.occurrence_check import OccurrenceCheck, OccurrenceCheckRequestError
from platosi.profiles import select
from platosi.registry import Registry
from platosi.unicode_search import key


VERSION = 1
MAX_FORMS = 500
MAX_LEMMA_FORMS = 10000
MAX_LEMMA_RELATIONS = 100
LIMIT = 20
PROVIDER_ERRORS = (OSError, RuntimeError, ValueError, ImportError, sqlite3.Error)
RELATION_TYPES = {
    "alternate_headword",
    "spelling_variant",
    "dialect_variant",
    "derived_noun",
    "derived_adjective",
    "derived_adverb",
    "prefixed_compound",
    "compound",
    "dictionary_cross_reference",
    "etymological_relation",
}


class InvalidRequest(ValueError):
    pass


def required_text(payload, name, maximum=10000):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InvalidRequest(f"{name} must be nonempty text of at most {maximum} characters")
    return value.strip()


class ReaderApi:
    def __init__(self, root):
        self.root = Path(root)
        self._registry_lock = threading.Lock()
        self._current_registry = None
        self._registry_fingerprint = None
        self._registry_users = {}
        self._retired_registries = set()
        self._closed = False

    def _configuration_fingerprint(self):
        paths = sorted((self.root / "plugins").glob("*/plugin.json"))
        config = self.root / "data" / "plugin-config.json"
        if config.exists():
            paths.append(config)
        return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)

    @contextmanager
    def _registry_lease(self):
        fingerprint = self._configuration_fingerprint()
        close_before_use = None
        with self._registry_lock:
            if self._closed:
                raise RuntimeError("Reader API is closed")
            if self._current_registry is None or fingerprint != self._registry_fingerprint:
                previous = self._current_registry
                self._current_registry = Registry(self.root)
                self._registry_fingerprint = fingerprint
                if previous is not None:
                    self._retired_registries.add(previous)
                    if self._registry_users.get(previous, 0) == 0:
                        self._retired_registries.remove(previous)
                        close_before_use = previous
            registry = self._current_registry
            self._registry_users[registry] = self._registry_users.get(registry, 0) + 1
        try:
            if close_before_use is not None:
                close_before_use.close()
            yield registry
        finally:
            close_after_use = None
            with self._registry_lock:
                users = self._registry_users[registry] - 1
                if users:
                    self._registry_users[registry] = users
                else:
                    self._registry_users.pop(registry)
                    if registry in self._retired_registries:
                        self._retired_registries.remove(registry)
                        close_after_use = registry
            if close_after_use is not None:
                close_after_use.close()

    def close(self):
        with self._registry_lock:
            if self._closed:
                return
            self._closed = True
            if self._current_registry is not None:
                self._retired_registries.add(self._current_registry)
                self._current_registry = None
            registries = [
                registry for registry in self._retired_registries
                if self._registry_users.get(registry, 0) == 0
            ]
            self._retired_registries.difference_update(registries)
        for registry in registries:
            registry.close()

    def resources(self, registry, capability):
        selection, active = select(registry, capability, tolerate_errors=True)
        problems = [item for item in selection
                    if item["id"] in registry.providers
                    and capability in registry.providers[item["id"]].manifest["capabilities"]
                    and (item["reason"] == "source or current index unavailable"
                         or (item["reason"] and item["reason"].startswith("provider error:")))]
        return active, problems

    @staticmethod
    def provider_artifacts(provider, capability=None):
        metadata = getattr(provider, "artifact_metadata", None)
        if not callable(metadata):
            return None, None
        artifacts = metadata()
        scoped = getattr(provider, "artifact_metadata_for", None)
        cache_artifacts = scoped(capability) if capability and callable(scoped) else artifacts
        return artifacts, cache_artifacts

    def capabilities(self, registry):
        definitions = [
            ("word.analyze", "Word and dictionary", ("analyze", "lookup")),
            ("linguistics.evidence", "Canonical word evidence", ("analyze", "lookup")),
            ("linguistics.dialogue-lexicon", "Dialogue forms and related lemmas",
             ("analyze", "lookup", "lemma_forms", "lemma_relations")),
            ("linguistics.person-research", "Grounded proper-name research",
             ("analyze", "lookup", "chat")),
            ("linguistics.verify-occurrences", "Bounded source-specific occurrence checks", ("analyze",)),
            ("lemma.matchForms", "Forms of a lemma", ("match_forms",)),
            ("text.search", "Find Greek text", ("search",)),
            ("text.passage", "Open a passage", ("passage",)),
            ("inquiry.ask", "Ask about a passage", ("search", "passage", "chat")),
        ]
        result = []
        for operation, title, requirements in definitions:
            parts = []
            for requirement in requirements:
                active, problems = self.resources(registry, requirement)
                parts.append({"capability": requirement, "available": bool(active), "issues": problems})
            if operation == "word.analyze":
                available = any(part["available"] for part in parts)
            elif operation == "linguistics.evidence":
                available = any(part["available"] for part in parts)
            elif operation == "linguistics.dialogue-lexicon":
                available = parts[0]["available"] and (parts[2]["available"] or parts[4]["available"])
            elif operation == "inquiry.ask":
                available = parts[2]["available"] and (parts[0]["available"] or parts[1]["available"])
            else:
                available = all(part["available"] for part in parts)
            result.append({"operation": operation, "title": title, "available": available, "parts": parts})
        inventory_exists = (self.root / INVENTORY).is_file()
        corpus = CanonicalCorpus(self.root) if inventory_exists else None
        canonical_selection_available = bool(corpus and corpus.any_available())
        for operation in ("linguistics.evidence", "linguistics.dialogue-lexicon",
                          "linguistics.person-research", "linguistics.verify-occurrences"):
            linguistic = next(item for item in result if item["operation"] == operation)
            linguistic["parts"].append({
                "capability": "canonical-text",
                "available": canonical_selection_available,
                "issues": [] if canonical_selection_available
                else ["Canonical corpus is not installed; run scripts/build-canonical-corpus.py."],
            })
            linguistic["available"] = linguistic["available"] and canonical_selection_available
        for operation, title in (("canonical.catalog", "Canonical dialogue catalogue"),
                                 ("canonical.work", "Canonical dialogue text"),
                                 ("canonical.resolve", "Resolve canonical location")):
            available = bool(corpus and (corpus.available() if operation == "canonical.catalog"
                                         else corpus.any_available()))
            issues = [] if available else ["Canonical corpus is not installed; run scripts/build-canonical-corpus.py."]
            result.append({"operation": operation, "title": title, "available": available,
                           "parts": [{"capability": "canonical-text", "available": available, "issues": issues}]})
        result.append({"operation": "system.info", "title": "Service version", "available": True, "parts": []})
        return {"capabilities": result}

    def collect(self, registry, capability, call):
        active, problems = self.resources(registry, capability)
        records = []
        warnings = [f"{item['id']}: {item['reason']}" for item in problems]
        succeeded = 0
        truncated = False
        for registration, provider in active:
            try:
                found = call(provider)
                if not isinstance(found, list):
                    raise ValueError("Provider returned an invalid result")
                records.extend(found)
                succeeded += 1
                if len(found) >= LIMIT and capability != "match_forms":
                    truncated = True
                    warnings.append(f"{registration.manifest['id']}: results may be limited to {LIMIT}.")
            except PROVIDER_ERRORS as error:
                warnings.append(f"{registration.manifest['id']}: {type(error).__name__}: {error}")
        if not active or not succeeded:
            status = "unavailable"
        elif warnings:
            status = "partial"
        else:
            status = "ok"
        return {"status": status, "records": records, "warnings": warnings, "possibly_truncated": truncated}

    def analyze(self, registry, payload):
        form = required_text(payload, "form", 200)
        analyses = self.collect(registry, "analyze", lambda provider: provider.analyze(form, "exact", LIMIT))
        queries = list(dict.fromkeys([form] + [item["lemma"] for item in analyses["records"]
                                              if isinstance(item.get("lemma"), str) and item["lemma"]]))
        entries = self.collect(registry, "lookup", lambda provider: self.lookup_entries(provider, queries))
        return {"form": form, "analyses": analyses, "entries": entries,
                "limitations": "Analyses are source-specific candidates, not verified contextual readings."}

    def linguistic_evidence(self, registry, payload):
        evidence = self.canonical_word_evidence(registry, payload, "linguistics.evidence")
        return {
            "contract": "platosi.linguistic-evidence.v1",
            "target": evidence["target"],
            "possibilities": evidence["possibilities"],
            "dictionary": evidence["dictionary"],
            "morphology": {"status": "not_requested"},
            "warnings": list(dict.fromkeys(evidence["warnings"])),
            "principle": "Evidence is presented without selecting or interpreting a contextual meaning.",
        }

    def canonical_word_evidence(self, registry, payload, operation):
        target = self.canonical_word_target(payload, operation)
        analyses = self.collect(
            registry,
            "analyze",
            lambda provider: provider.analyze(target["text"], "exact", LIMIT),
        )
        return self.word_evidence_from_records(
            registry, target, analyses["records"], analyses["warnings"]
        )

    def canonical_word_target(self, payload, operation):
        if set(payload) != {"location"}:
            raise InvalidRequest(f"{operation} requires only a location")
        try:
            target = CanonicalCorpus(self.root).resolve(payload.get("location"))
        except LocationError as error:
            raise InvalidRequest(str(error)) from error
        form = unicodedata.normalize("NFC", target["text"].strip())
        if (not form or len(form) > 200 or form != target["text"]
                or any(not self.greek_word_character(char) for char in form)):
            raise InvalidRequest("location must select exactly one Greek word without punctuation")
        return target

    def word_evidence_from_records(self, registry, target, records, analysis_warnings=()):
        possibilities = self.organize_possibilities(records)
        queries = list(dict.fromkeys(
            [target["text"]]
            + [
                item["lemma"]
                for item in records
                if isinstance(item.get("lemma"), str) and item["lemma"]
            ]
        ))
        entries = self.collect(
            registry, "lookup", lambda provider: self.lookup_entries(provider, queries)
        )
        dictionary = {
            "status": entries["status"],
            "entries": [self.organize_dictionary_entry(record)
                        for record in entries["records"]],
            "warnings": entries["warnings"],
            "possibly_truncated": entries["possibly_truncated"],
        }
        warnings = [*analysis_warnings, *dictionary["warnings"]]
        return {
            "target": target,
            "possibilities": possibilities,
            "dictionary": dictionary,
            "warnings": list(dict.fromkeys(warnings)),
        }

    @staticmethod
    def greek_word_character(char):
        category = unicodedata.category(char)
        return (category.startswith("L") and "GREEK" in unicodedata.name(char, "")) or category.startswith("M")

    @staticmethod
    def organize_possibilities(records):
        grouped = {}
        seen = {}
        for record in records:
            lemma = record.get("lemma")
            if not isinstance(lemma, str) or not lemma:
                continue
            analysis = record.get("analysis") if isinstance(record.get("analysis"), dict) else {}
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            license_record = record.get("license") if isinstance(record.get("license"), dict) else {}
            settings = record.get("settings") if isinstance(record.get("settings"), dict) else {}
            candidate = {
                "provider": record.get("provider"),
                "provider_version": record.get("provider_version"),
                "method": record.get("method"),
                "classification": record.get("classification"),
                "language": analysis.get("lang"),
                "proper": analysis.get("proper"),
                "rank": analysis.get("score"),
                "via": analysis.get("via"),
                "tag": analysis.get("tag"),
                "citation": analysis.get("citation"),
                "headword": analysis.get("headword"),
                "homograph": analysis.get("homograph"),
                "features": analysis.get("features"),
                "settings": settings,
                "supporting_settings": [settings],
                "source": source,
                "license": license_record,
            }
            identity = json.dumps({
                key: value for key, value in candidate.items()
                if key not in ("settings", "supporting_settings")
            },
                                  ensure_ascii=False, sort_keys=True)
            lemma_seen = seen.setdefault(lemma, {})
            if identity in lemma_seen:
                existing = lemma_seen[identity]
                if settings not in existing["supporting_settings"]:
                    existing["supporting_settings"].append(settings)
                continue
            lemma_seen[identity] = candidate
            grouped.setdefault(lemma, []).append(candidate)
        return [{"lemma": lemma, "candidates": candidates} for lemma, candidates in grouped.items()]

    @staticmethod
    def organize_dictionary_entry(record):
        xml = record.get("entry_xml")
        plain_text = None
        if isinstance(xml, str):
            try:
                plain_text = " ".join(part.strip() for part in ET.fromstring(xml).itertext()
                                      if part.strip())
            except ET.ParseError:
                plain_text = None
        return {
            "provider": record.get("provider"),
            "provider_version": record.get("provider_version"),
            "headword": record.get("headword"),
            "matched_term": record.get("matched_term"),
            "match_kind": record.get("match_kind"),
            "match_fragment": record.get("match_fragment"),
            "entry_id": record.get("entry_id"),
            "entry_xml": xml,
            "plain_text": plain_text,
            "source": record.get("source") if isinstance(record.get("source"), dict) else {},
            "license": record.get("license") if isinstance(record.get("license"), dict) else {},
        }


    def dialogue_lexicon(self, registry, payload):
        target = self.canonical_word_target(payload, "linguistics.dialogue-lexicon")
        form_providers, form_problems = self.resources(registry, "lemma_forms")
        relation_providers, relation_problems = self.resources(registry, "lemma_relations")
        dictionary_providers, dictionary_problems = self.resources(registry, "lookup")

        def metadata(registration, provider, capability):
            artifacts, cache_artifacts = self.provider_artifacts(provider, capability)
            scoped_configuration = getattr(provider, "configuration_for", None)
            cache_config = (
                scoped_configuration(capability)
                if callable(scoped_configuration)
                else registration.manifest.get("config", {})
            )
            return {
                "id": registration.manifest["id"],
                "version": registration.manifest["version"],
                "source": registration.manifest["source"],
                "config": registration.manifest.get("config", {}),
                "artifacts": artifacts,
                "cache_config": cache_config,
                "cache_artifacts": cache_artifacts,
            }

        form_sources = [(registration, provider, metadata(registration, provider, "lemma_forms"))
                        for registration, provider in form_providers]
        relation_sources = [(registration, provider, metadata(registration, provider, "lemma_relations"))
                            for registration, provider in relation_providers]

        def fingerprint(sources):
            value = json.dumps(
                [{
                    "id": item[2]["id"],
                    "version": item[2]["version"],
                    "source": item[2]["source"],
                    "cache_config": item[2]["cache_config"],
                    "cache_artifacts": item[2]["cache_artifacts"],
                } for item in sources],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            return hashlib.sha256(value.encode("utf-8")).hexdigest()

        form_fingerprint = fingerprint(form_sources)
        relation_fingerprint = fingerprint(relation_sources)
        location = target["location"]
        index = DialogueLexiconIndex(self.root)
        morphology_index = DialogueMorphologyIndex(self.root)
        with index.request_context(location["dialogue"], location["text_version"]) as context:
            morphology = morphology_index.latest(context)
            if morphology is None:
                morphology_records = []
                morphology_warnings = [
                    "No completed local dialogue morphology index is available; "
                    "build it before requesting occurrence counts."
                ]
            else:
                morphology_records = morphology_index.form_records(
                    context, morphology["build_id"], target["text"]
                )
                morphology_warnings = []
                if not morphology_records:
                    morphology_warnings.append(
                        f"{morphology['provider']}: the completed dialogue index has "
                        f"no morphological analysis for {target['text']}."
                    )
            evidence = self.word_evidence_from_records(
                registry, target, morphology_records, morphology_warnings
            )
            warnings = [*evidence["warnings"], *[
                f"{item['id']}: {item['reason']}"
                for item in [*form_problems, *relation_problems, *dictionary_problems]
            ]]
            result = self._dialogue_lexicon_result(
                evidence,
                warnings,
                form_sources,
                relation_sources,
                form_fingerprint,
                relation_fingerprint,
                index,
                context,
                dictionary_providers,
                morphology_index,
                morphology,
            )
        analysis_ids = sorted({
            candidate["provider"]
            for possibility in evidence["possibilities"]
            for candidate in possibility["candidates"]
            if isinstance(candidate.get("provider"), str)
        })
        inventory_ids = {
            registration.manifest["id"] for registration, _ in form_providers
        }
        if morphology is not None:
            inventory_ids.add(morphology["provider"])
        inventory_ids = sorted(inventory_ids)
        analysis_only = [provider_id for provider_id in analysis_ids
                         if provider_id not in inventory_ids]
        provider_metadata = {item["id"]: item for item in result["providers"]}
        for provider_id in analysis_ids:
            if provider_id not in provider_metadata and provider_id in registry.providers:
                registration = registry.providers[provider_id]
                provider_metadata[provider_id] = metadata(registration, registration.load(), "analyze")
        if morphology is not None and morphology["provider"] not in provider_metadata:
            stored = morphology["provider_metadata"]
            provider_metadata[morphology["provider"]] = {
                "id": stored["id"],
                "version": stored["version"],
                "source": stored["source"],
                "license": stored["license"],
                "config": stored["identity"],
                "artifacts": None,
                "cache_config": None,
                "cache_artifacts": None,
            }
        result["providers"] = [provider_metadata[provider_id] for provider_id in sorted(provider_metadata)]
        result["coverage"] = {
            "analysis_providers": analysis_ids,
            "form_inventory_providers": inventory_ids,
            "analysis_only_providers": analysis_only,
            "morphology_index_providers": [] if morphology is None else [morphology["provider"]],
            "morphology_indexes": [] if morphology is None else [morphology],
            "cached_analysis_providers": [],
            "cached_form_coverage": [],
        }
        result["warnings"].extend(
            f"{provider_id}: supplies selected-word analyses, not a complete dialogue form inventory; "
            f"occurrence counts are not verified by {provider_id}."
            for provider_id in analysis_only
        )
        return result

    def _dialogue_lexicon_result(
        self,
        evidence,
        warnings,
        form_sources,
        relation_sources,
        form_fingerprint,
        relation_fingerprint,
        index,
        context,
        dictionary_providers,
        morphology_index,
        morphology,
    ):
        location = evidence["target"]["location"]

        definitions = {}

        def load_definitions(lemma):
            if lemma not in definitions:
                entries, problems = [], []
                truncated = False
                succeeded = 0
                for registration, provider in dictionary_providers:
                    try:
                        found = provider.lookup(lemma, "exact", 4)
                        if not isinstance(found, list) or any(not isinstance(item, dict) for item in found):
                            raise ValueError("Provider returned invalid related-lemma dictionary entries")
                        truncated = truncated or len(found) > 3
                        for record in found[:3]:
                            entries.append(self.organize_dictionary_entry(record))
                        succeeded += 1
                    except PROVIDER_ERRORS as error:
                        message = f"{registration.manifest['id']}: related definition failed for {lemma}: {type(error).__name__}: {error}"
                        problems.append(message)
                        warnings.append(message)
                status = ("partial" if problems and succeeded else "unavailable" if not succeeded
                          else "ok" if entries else "empty")
                definitions[lemma] = {"status": status, "entries": entries,
                                      "possibly_truncated": truncated, "warnings": problems}
            return definitions[lemma]

        def load_forms(lemma, candidates=None):
            records = index.cached_lemma_forms(
                location["dialogue"],
                location["text_version"],
                lemma,
                form_fingerprint,
                context=context,
            )
            if not form_sources:
                records = []
            cache_hit = records is not None and bool(form_sources)
            if records is None:
                records = []
                complete = True
                for registration, provider, _metadata in form_sources:
                    try:
                        found = provider.lemma_forms(lemma, MAX_LEMMA_FORMS)
                        if not isinstance(found, list):
                            raise ValueError("Provider returned an invalid lemma form inventory")
                        for record in found:
                            if (not isinstance(record, dict)
                                    or not isinstance(record.get("form"), str)
                                    or key(record.get("lemma", "")) != key(lemma)):
                                raise ValueError("Provider returned a form for a different lemma")
                        records.extend(found)
                    except PROVIDER_ERRORS as error:
                        complete = False
                        warnings.append(
                            f"{registration.manifest['id']}: lemma forms failed: "
                            f"{type(error).__name__}: {error}"
                        )
                if complete:
                    records = index.store_lemma_forms(
                        location["dialogue"],
                        location["text_version"],
                        lemma,
                        form_fingerprint,
                        records,
                        context=context,
                    )
            if morphology is not None:
                identities = {
                    (candidate.get("headword"), candidate.get("homograph"))
                    for candidate in candidates or []
                    if candidate.get("provider") == morphology["provider"]
                    and candidate.get("headword")
                }
                records.extend(morphology_index.lemma_records(
                    context,
                    morphology["build_id"],
                    lemma,
                    identities or None,
                ))
            observed = index.observed_records(
                location["dialogue"], location["text_version"], records, context=context,
            )
            return observed, cache_hit

        def load_relations(lemma):
            records = index.cached_lemma_relations(
                location["dialogue"],
                location["text_version"],
                lemma,
                relation_fingerprint,
                context=context,
            )
            cache_hit = records is not None
            if records is None:
                records = []
                complete = True
                for registration, provider, _metadata in relation_sources:
                    try:
                        found = provider.lemma_relations(lemma, MAX_LEMMA_RELATIONS)
                        if not isinstance(found, list):
                            raise ValueError("Provider returned an invalid lemma relation inventory")
                        for record in found:
                            if (not isinstance(record, dict)
                                    or key(record.get("source_lemma", "")) != key(lemma)
                                    or not isinstance(record.get("target_lemma"), str)
                                    or record.get("relation_type") not in RELATION_TYPES):
                                raise ValueError("Provider returned an invalid lemma relation")
                        records.extend(found)
                    except PROVIDER_ERRORS as error:
                        complete = False
                        warnings.append(
                            f"{registration.manifest['id']}: lemma relations failed: "
                            f"{type(error).__name__}: {error}"
                        )
                if complete:
                    records = index.store_lemma_relations(
                        location["dialogue"],
                        location["text_version"],
                        lemma,
                        relation_fingerprint,
                        records,
                        context=context,
                    )
            return records, cache_hit

        lemmas = []
        for possibility in evidence["possibilities"]:
            lemma = possibility["lemma"]
            forms, form_cache_hit = load_forms(lemma, possibility["candidates"])
            relation_records, relation_cache_hit = load_relations(lemma)
            grouped_relations = {}
            for record in relation_records:
                identity = (
                    key(record["target_lemma"]),
                    record["relation_type"],
                    record.get("direction", "directed"),
                )
                group = grouped_relations.setdefault(identity, {
                    "lemma": record["target_lemma"],
                    "relation_type": record["relation_type"],
                    "direction": record.get("direction", "directed"),
                    "evidence": [],
                })
                group["evidence"].append(record)
            related_lemmas = []
            for group in grouped_relations.values():
                related_forms, _ = load_forms(group["lemma"])
                count = sum(item["count"] for item in related_forms)
                related_lemmas.append({
                    **group,
                    "present_in_dialogue": count > 0,
                    "count": count,
                    "forms": related_forms,
                    "dictionary": load_definitions(group["lemma"]),
                })
            related_lemmas.sort(
                key=lambda item: (
                    not item["present_in_dialogue"],
                    item["relation_type"],
                    key(item["lemma"]),
                )
            )
            lemmas.append({
                "lemma": lemma,
                "candidates": possibility["candidates"],
                "forms": forms,
                "related_lemmas": related_lemmas,
                "cache": {
                    "hit": form_cache_hit and relation_cache_hit,
                    "forms_hit": form_cache_hit,
                    "relations_hit": relation_cache_hit,
                    "form_provider_fingerprint": form_fingerprint,
                    "relation_provider_fingerprint": relation_fingerprint,
                },
            })
        provider_metadata = {}
        for _, _, item in [*form_sources, *relation_sources]:
            provider_metadata[item["id"]] = item
        return {
            "contract": "platosi.dialogue-lexicon.v1",
            "target": evidence["target"],
            "lemmas": lemmas,
            "dictionary": evidence["dictionary"],
            "morphology": {"status": "not_requested"},
            "providers": [provider_metadata[item] for item in sorted(provider_metadata)],
            "warnings": list(dict.fromkeys(warnings)),
            "limitations": (
                "Forms use source headword mappings; cached analyses cover only currently cached forms, "
                "with homographs kept separate. Compatible morphology is not contextual verification. "
                "Related lemmas include explicit configured "
                "source relations only; spelling similarity and model inference are excluded."
            ),
        }

    @staticmethod
    def lookup_entries(provider, queries):
        result = []
        for query in queries:
            remaining = LIMIT - len(result)
            if remaining <= 0:
                break
            result.extend(provider.lookup(query, "exact", remaining))
        return result

    def match_forms(self, registry, payload):
        lemma = required_text(payload, "lemma", 200)
        forms = payload.get("forms")
        if (not isinstance(forms, list) or not 1 <= len(forms) <= MAX_FORMS
                or any(not isinstance(form, str) or not form.strip() or len(form) > 200 for form in forms)
                or len(set(forms)) != len(forms)):
            raise InvalidRequest(f"forms must contain 1 to {MAX_FORMS} distinct nonempty forms")
        result = self.collect(registry, "match_forms", lambda provider: provider.match_forms(lemma, forms))
        original = {}
        for form in forms:
            original.setdefault(key(form), []).append(form)
        matches = []
        for record in result["records"]:
            if not isinstance(record.get("form"), str) or not isinstance(record.get("lemma"), str):
                raise ValueError("Morphology provider returned an invalid form mapping")
            if key(record["lemma"]) != key(lemma) or key(record["form"]) not in original:
                raise ValueError("Morphology provider returned a mapping outside the request")
            for form in original[key(record["form"])]:
                matches.append({"input_form": form, "evidence": record})
        result["records"] = matches
        result["limitations"] = "Direct mappings are candidates and may be incomplete or contextually incorrect."
        return result


    def person_research(self, registry, payload, cancellation):
        if set(payload) != {"location", "lemma"}:
            raise InvalidRequest("linguistics.person-research requires a location and lemma")
        lemma = required_text(payload, "lemma", 200)
        try:
            target = CanonicalCorpus(self.root).resolve(payload.get("location"))
        except LocationError as error:
            raise InvalidRequest(str(error)) from error
        form = unicodedata.normalize("NFC", target["text"].strip())
        analyses = self.collect(
            registry, "analyze", lambda provider: provider.analyze(form, "exact", LIMIT)
        )
        possibilities = self.organize_possibilities(analyses["records"])
        possibility = next((item for item in possibilities if item["lemma"] == lemma), None)
        if possibility is None:
            raise InvalidRequest("lemma is not a candidate for the selected form")
        proper_candidates = [
            item for item in possibility["candidates"] if item.get("proper") is True
        ]
        if not proper_candidates:
            return {
                "contract": "platosi.person-research.v3",
                "status": "not_candidate",
                "lemma": lemma,
                "target": target,
                "classification": {
                    "proper_name_candidate": False,
                    "basis": "No morphology provider returned a capitalized-headword candidate.",
                    "evidence": possibility["candidates"],
                },
                "overview": "",
                "sources": [],
                "candidates": [],
                "model": None,
                "cache": {},
                "warnings": analyses["warnings"],
            }
        research = PersonResearch(self.root)
        provider = None
        model_identity = {}
        model_problem = None
        try:
            registration, provider = model_provider(registry, None, "chat")
            configured_model = registration.manifest.get("config", {}).get("model")
            model_record = None
            if callable(getattr(provider, "list_models", None)):
                model_record = next(
                    (item for item in provider.list_models()
                     if item.get("name") == configured_model), None,
                )
            model_identity = {
                "provider": registration.manifest["id"],
                "provider_version": registration.manifest["version"],
                "model": configured_model,
                "digest": model_record.get("digest") if isinstance(model_record, dict) else None,
            }
        except (ValueError, RuntimeError, OSError, TimeoutError) as error:
            model_problem = f"{type(error).__name__}: {error}"

        def model_call(prompt, schema):
            cancellation.check()
            if model_problem or provider is None:
                raise RuntimeError(model_problem or "No research model is available")
            return provider.chat(
                [{"role": "user", "content": prompt}],
                {"response_format": "json", "response_schema": schema,
                 "max_tokens": research.configuration.max_tokens},
                cancellation,
            )

        context = "\n".join(
            f"[{item['stephanus']}] {item['text']}" for item in target["context"]
        )[:4000]
        result = research.research(
            lemma,
            context,
            model_call,
            model_identity,
            target["location"]["dialogue"],
        )
        result["target"] = target
        result["classification"] = {
            "proper_name_candidate": True,
            "basis": (
                "A morphology provider returned a capitalized-headword candidate; "
                "this is not contextual named-entity recognition."
            ),
            "evidence": proper_candidates,
        }
        result["warnings"] = list(dict.fromkeys([
            *analyses["warnings"],
            *result["warnings"],
        ]))
        return result

    def ask(self, registry, payload, cancellation):
        question = required_text(payload, "question", 4000)
        text = payload.get("text")
        edition = payload.get("edition")
        citation = payload.get("citation")
        location = payload.get("location")
        if location is not None:
            if text is not None or edition is not None or citation is not None:
                raise InvalidRequest("Supply a location without text, edition, or citation")
            text = CanonicalCorpus(self.root).resolve(location)["text"]
        if text is not None:
            if location is None:
                text = required_text(payload, "text", 4000)
            elif len(text) > 4000:
                raise InvalidRequest("Selected canonical text exceeds 4000 characters")
        if edition is not None:
            edition = required_text(payload, "edition", 500)
        if citation is not None:
            citation = required_text(payload, "citation", 100)
        if bool(text) == bool(edition and citation) or bool(edition) != bool(citation):
            raise InvalidRequest("Supply a PlatoSI location, Greek text, or an edition and citation")
        registration, _ = model_provider(registry, None, "chat")
        resources = [pid for pid, item in registry.providers.items() if item.manifest["type"] != "language-model"]
        profile = {"resources": resources, "text_first": False}

        def generate(provider, prompt, options):
            cancellation.check()
            return provider.chat([{"role": "user", "content": prompt}], options, cancellation)

        result = inquire(registry, question, profile=profile, text=text, edition=edition, citation=citation,
                         model_id=registration.manifest["id"], generate_response=generate)
        cancellation.check()
        return result

    def execute(self, operation, payload, cancellation=None):
        if not isinstance(payload, dict):
            raise InvalidRequest("payload must be an object")
        cancellation = cancellation or Cancellation()
        cancellation.check()
        if operation.startswith("canonical.") or operation == "system.info":
            return self._execute(operation, payload, cancellation, None)
        with self._registry_lease() as registry:
            return self._execute(operation, payload, cancellation, registry)

    def _execute(self, operation, payload, cancellation, registry):
        if operation == "system.info":
            if payload:
                raise InvalidRequest("system.info requires an empty payload")
            result = {"service": "PlatoSI", "version": __version__, "protocol_version": VERSION,
                      "location_contract": CONTRACT}
        elif operation == "capabilities":
            result = self.capabilities(registry)
        elif operation == "word.analyze":
            result = self.analyze(registry, payload)
        elif operation == "linguistics.evidence":
            result = self.linguistic_evidence(registry, payload)
        elif operation == "linguistics.dialogue-lexicon":
            result = self.dialogue_lexicon(registry, payload)
        elif operation == "linguistics.verify-occurrences":
            try:
                result = OccurrenceCheck(self.root).run(registry, payload, cancellation)
            except OccurrenceCheckRequestError as error:
                raise InvalidRequest(str(error)) from error
        elif operation == "linguistics.person-research":
            result = self.person_research(registry, payload, cancellation)
        elif operation == "lemma.matchForms":
            result = self.match_forms(registry, payload)
        elif operation == "text.search":
            query = required_text(payload, "text", 4000)
            result = self.collect(registry, "search", lambda provider: provider.search(query, "exact", LIMIT))
        elif operation == "text.passage":
            edition = required_text(payload, "edition", 500)
            citation = required_text(payload, "citation", 100)
            result = self.collect(registry, "passage", lambda provider: provider.passage(edition, citation))
        elif operation == "inquiry.ask":
            result = self.ask(registry, payload, cancellation)
        elif operation in ("canonical.catalog", "canonical.work", "canonical.resolve"):
            try:
                corpus = CanonicalCorpus(self.root)
                if operation == "canonical.catalog":
                    result = corpus.catalogue()
                elif operation == "canonical.resolve":
                    if set(payload) != {"location"}:
                        raise InvalidRequest("canonical.resolve requires only a location")
                    result = corpus.resolve(payload.get("location"))
                else:
                    dialogue = required_text(payload, "dialogue", 200)
                    version = payload.get("text_version")
                    if version is not None:
                        version = required_text(payload, "text_version", 100)
                    result = corpus.work(dialogue, version)
                    division = payload.get("division")
                    if division is not None:
                        if not isinstance(division, dict) or set(division) != {"type", "label"}:
                            raise InvalidRequest("division must contain type and label")
                        if not all(isinstance(division[key], str) and division[key] for key in ("type", "label")):
                            raise InvalidRequest("division type and label must be nonempty strings")
                        sections = [section for section in result["sections"] if section["division"] == division]
                        if not sections:
                            raise InvalidRequest("Unknown dialogue division")
                        result = {**result, "sections": sections, "division": division}
            except LocationError as error:
                raise InvalidRequest(str(error)) from error
        else:
            raise InvalidRequest("Unknown operation")
        cancellation.check()
        return result
