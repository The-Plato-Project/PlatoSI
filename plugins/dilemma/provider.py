"""Optional Dilemma adapter; candidates remain unverified and non-exhaustive."""

import dataclasses
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from platosi.storage import read_index
from platosi.unicode_search import key


class DilemmaProvider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.root = root
        self.data = (root / manifest["config"]["data"]).resolve()
        self.model = (root / manifest["config"]["model"]).resolve()
        self.tagger = (root / manifest["config"]["tagger"]).resolve()
        self.paradigm_data = (root / manifest["config"]["paradigm_data"]).resolve()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dilemma")
        self.engines = {}
        self.taggers = {}
        self.loaded_artifacts = None

    @staticmethod
    def evaluation_catalog():
        return [
            {"id": "analyze", "title": "Lemmatization and ambiguity",
             "description": "Compare verbose candidates, optional POS selection, guessing, and attestation filters.",
             "presets": [
                 {"name": "Republic opening form", "options": {"form": "κατέβην", "with_attestation": True}},
                 {"name": "Ambiguous pronoun", "options": {"form": "αὐτοῦ", "resolve_articles": True}},
             ]},
            {"id": "batch", "title": "Batch lemmatization",
             "description": "Resolve a sequence with optional UPOS hints.",
             "presets": [{"name": "Republic forms", "options": {
                 "words": ["κατέβην", "προσευξόμενος", "βουλόμενος"],
                 "upos_tags": ["VERB", "VERB", "VERB"]}}]},
            {"id": "predict_pos", "title": "POS prediction",
             "description": "Predict universal parts of speech for independent forms.",
             "presets": [{"name": "Ambiguous forms", "options": {
                 "words": ["κατέβην", "τοῦ", "αὐτοῦ", "πομπή"]}}]},
            {"id": "attestation", "title": "Attestation and citations",
             "description": "Inspect lemma and exact-form counts, works, and corpus citations.",
             "presets": [{"name": "κατέβην evidence", "options": {
                 "lemma": "καταβαίνω", "form": "κατέβην", "max_citations": 10}}]},
            {"id": "spelling", "title": "Spelling suggestions",
             "description": "Test edit-distance, OCR, headword, and lemma-constrained suggestions.",
             "presets": [{"name": "Unaccented form", "options": {
                 "form": "κατεβην", "max_distance": 2, "ocr_mode": False}}]},
            {"id": "headwords", "title": "Headword inventory",
             "description": "Check a convention-specific headword and optionally inspect a range.",
             "presets": [{"name": "LSJ range", "options": {
                 "word": "καταβαίνω", "end": "κατάβασις", "headword_convention": "lsj"}}]},
            {"id": "repair", "title": "Lemma repair",
             "description": "Exercise Dilemma's optional headword-backed repair path.",
             "presets": [{"name": "Repair candidate", "options": {
                 "lemma": "καταβαινω", "form": "κατέβην"}}]},
            {"id": "tagger", "title": "Contextual tagger and parser",
             "description": "Run sentence segmentation, lemmatization, UPOS, features, and dependency parsing.",
             "presets": [{"name": "Republic 327a", "options": {
                 "text": "Κατέβην χθὲς εἰς Πειραιᾶ μετὰ Γλαύκωνος τοῦ Ἀρίστωνος.",
                 "segment_text": True, "lemmatize": True}}]},
            {"id": "paradigm", "title": "Paradigm generation",
             "description": "Compare generated and attested forms with citations.",
             "presets": [
                 {"name": "Verb paradigm", "options": {
                     "lemma": "καταβαίνω", "pos": "verb", "with_attestation": True}},
                 {"name": "Noun paradigm", "options": {
                     "lemma": "πομπή", "pos": "noun", "with_attestation": True}},
             ]},
            {"id": "generate", "title": "Generate one paradigm slot",
             "description": "Request one explicitly described morphological slot.",
             "presets": [{"name": "Aorist indicative", "options": {
                 "lemma": "γράφω", "slot": {"pos": "verb", "voice": "act", "tense": "aor",
                                             "mood": "ind", "person": "1", "number": "sg"},
                 "with_attestation": True}}]},
            {"id": "morphology_diff", "title": "Morphology comparison",
             "description": "Explain differences between a lemma and form or compare named paradigm forms.",
             "presets": [{"name": "Aorist morphology", "options": {
                 "lemma": "γράφω", "form": "ἔγραψα"}}]},
            {"id": "reconcile", "title": "Source reconciliation",
             "description": "Inspect votes, disagreements, and deterministic correction rules.",
             "presets": [{"name": "Voice disagreement", "options": {
                 "form": "ὑπέσχετο", "readings": [
                     {"source": "source-a", "lemma": "ὑπισχνέομαι", "upos": "VERB",
                      "feats": {"Voice": "Act"}},
                     {"source": "source-b", "lemma": "ὑπισχνέομαι", "upos": "VERB",
                      "feats": {"Voice": "Mid"}},
                 ]}}]},
            {"id": "normalization", "title": "Unicode and editorial normalization",
             "description": "Show accent, monotonic, editorial, capitalization, elision, and sanitization helpers.",
             "presets": [{"name": "Editorial forms", "options": {
                 "text": "Κατέβην· κατ’ αὐτοῦ"}}]},
            {"id": "nonlexical", "title": "Nonlexical classification",
             "description": "Classify punctuation, numerals, editorial tokens, and lexical forms.",
             "presets": [{"name": "Mixed tokens", "options": {
                 "forms": ["κατέβην", "·", "—", "123", "[…]"]}}]},
            {"id": "citation", "title": "Citation-form validation",
             "description": "Inspect tonal issues and strict Ancient Greek citation status.",
             "presets": [{"name": "Citation candidates", "options": {
                 "lemmas": ["καταβαίνω", "καταβαινω", "πομπή"]}}]},
            {"id": "lookup", "title": "Lookup database",
             "description": "Inspect direct form-to-lemma rows without inference.",
             "presets": [{"name": "Known and invented forms", "options": {
                 "forms": ["κατέβην", "πομπή", "ἀφλωποτήσσουσιν"]}}]},
            {"id": "cache", "title": "Preload and cache export",
             "description": "Load Dilemma's lookup cache and compare selected entries.",
             "presets": [{"name": "Cache sample", "options": {
                 "forms": ["κατέβην", "πομπή", "πέμπω"]}}]},
            {"id": "inventory", "title": "Package and artifact inventory",
             "description": "Inspect installed exports, artifact fingerprint, counts, sizes, and configured paths.",
             "presets": [{"name": "Current installation", "options": {}}]},
        ]

    def artifact_metadata(self):
        roots = (self.data, self.model, self.tagger, self.paradigm_data)
        files = []
        seen = set()
        for directory in roots:
            if directory in seen or not directory.is_dir():
                continue
            seen.add(directory)
            files.extend((str(p.relative_to(directory)), p.stat().st_size, p.stat().st_mtime_ns)
                         for p in sorted(directory.rglob("*")) if p.is_file())
        signature = hashlib.sha256(json.dumps(files, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {"declared_revision": self.manifest["config"].get("artifact_revision"),
                "revision_verified": False, "local_file_metadata_sha256": signature,
                "file_count": len(files), "total_bytes": sum(item[1] for item in files)}

    def available(self):
        if not (self.data / "lookup.db").is_file() or importlib.util.find_spec("dilemma") is None:
            return False
        try:
            return importlib.metadata.version("dilemma-nlp") == self.manifest["config"]["package_version"]
        except importlib.metadata.PackageNotFoundError:
            return False

    def _configure_environment(self):
        expected = {
            "DILEMMA_DATA_DIR": self.data,
            "DILEMMA_MODEL_DIR": self.model,
            "DILEMMA_TAGGER_DIR": self.tagger,
            "DILEMMA_PARADIGM_DATA": self.paradigm_data,
        }
        for name, path in expected.items():
            configured = os.environ.get(name)
            if configured and Path(configured).resolve() != path:
                raise ValueError(f"{name} does not match the Dilemma provider configuration")
            os.environ[name] = str(path)

    def _engine(self, options=None):
        options = options or {}
        settings = {
            "lang": "grc",
            "device": "cpu",
            "resolve_articles": self._boolean(options, "resolve_articles", False),
            "normalize": self._boolean(options, "normalize", False),
            "period": self._choice(options, "period",
                                   (None, "hellenistic", "late_antique", "byzantine", "all"), None),
            "dialect": self._choice(options, "dialect",
                                    (None, "ionic", "doric", "aeolic", "koine", "auto"), None),
            "convention": self._choice(options, "convention",
                                       (None, "wiktionary", "lsj", "cunliffe", "triantafyllidis"), None),
            "skip_pos": self._boolean(options, "skip_pos", False),
            "citation_policy": self._choice(options, "citation_policy",
                                            ("default", "strict_ag"), "default"),
        }
        cache_key = tuple(settings.items())
        if cache_key not in self.engines:
            self._configure_environment()
            from dilemma import Dilemma
            from dilemma.core import DATA_DIR
            if Path(DATA_DIR).resolve() != self.data:
                raise ValueError("Dilemma was already loaded with a different data directory")
            self.engines[cache_key] = Dilemma(**settings)
        return self.engines[cache_key]

    def _tagger(self, options):
        dialect = self._choice(options, "dialect",
                               (None, "ionic", "doric", "aeolic", "koine", "auto"), None)
        lemmatize = self._boolean(options, "lemmatize", True)
        cache_key = (dialect, lemmatize)
        if cache_key not in self.taggers:
            self._configure_environment()
            from dilemma import Tagger
            self.taggers[cache_key] = Tagger(lang="grc", device="cpu",
                                             dialect=dialect, lemmatize=lemmatize)
        return self.taggers[cache_key]

    def analyze(self, form, mode, limit):
        if mode != "exact":
            raise ValueError("Dilemma exploration supports exact NFC input only")
        form = key(form).strip()
        if not form:
            raise ValueError("Form is empty after normalization")
        return self.worker.submit(self._analyze, form, limit).result()

    def _analyze(self, form, limit):
        records = []
        artifacts = self.artifact_metadata()
        engines = [self._engine({"resolve_articles": setting, "skip_pos": True})
                   for setting in (False, True)]
        if self.loaded_artifacts is None:
            self.loaded_artifacts = artifacts
        elif artifacts != self.loaded_artifacts:
            raise ValueError("Dilemma data changed after initialization; restart the server")
        for setting, engine in zip((False, True), engines):
            for item in engine.lemmatize_verbose(form, guess=False):
                candidate = dataclasses.asdict(item)
                records.append({
                    "evidence_type": "candidate_analysis", "provider": self.manifest["id"],
                    "provider_version": self.manifest["version"], "source": self.manifest["source"],
                    "license": self.manifest["license"], "artifacts": artifacts,
                    "form": form, "lemma": candidate["lemma"], "analysis": candidate,
                    "method": candidate["source"], "settings": {"lang": "grc", "resolve_articles": setting,
                                                                  "guess": False},
                    "classification": "lookup_candidate" if candidate["source"] == "lookup"
                                      else "rule_generated_suggestion",
                    "limitations": "Candidates may be incomplete or incorrect; ranks are not certainty.",
                })
        return records[:limit]

    def evaluate(self, feature, options):
        if not isinstance(feature, str) or not feature:
            raise ValueError("feature must be nonempty text")
        if not isinstance(options, dict):
            raise ValueError("options must be an object")
        return self.worker.submit(self._evaluate, feature, options).result()

    def _evaluate(self, feature, options):
        operations = {
            "analyze": self._evaluate_analyze,
            "batch": self._evaluate_batch,
            "predict_pos": self._evaluate_predict_pos,
            "attestation": self._evaluate_attestation,
            "spelling": self._evaluate_spelling,
            "headwords": self._evaluate_headwords,
            "repair": self._evaluate_repair,
            "tagger": self._evaluate_tagger,
            "paradigm": self._evaluate_paradigm,
            "generate": self._evaluate_generate,
            "morphology_diff": self._evaluate_morphology_diff,
            "reconcile": self._evaluate_reconcile,
            "normalization": self._evaluate_normalization,
            "nonlexical": self._evaluate_nonlexical,
            "citation": self._evaluate_citation,
            "lookup": self._evaluate_lookup,
            "cache": self._evaluate_cache,
            "inventory": self._evaluate_inventory,
        }
        if feature not in operations:
            raise ValueError(f"Unknown Dilemma evaluation feature: {feature}")
        artifacts = self.artifact_metadata()
        if self.loaded_artifacts is None:
            self.loaded_artifacts = artifacts
        elif artifacts != self.loaded_artifacts:
            raise ValueError("Dilemma data changed after initialization; restart the server")
        started = __import__("time").perf_counter()
        result = operations[feature](options)
        elapsed = __import__("time").perf_counter() - started
        return {"feature": feature, "seconds": round(elapsed, 4),
                "artifacts": artifacts, "result": self._plain(result)}

    def _evaluate_analyze(self, options):
        form = self._text(options, "form")
        engine = self._engine(options)
        guess = self._boolean(options, "guess", False)
        attested_only = self._boolean(options, "attested_only", False)
        with_attestation = self._boolean(options, "with_attestation", False)
        previous = options.get("prev_word")
        if previous is not None:
            previous = self._text(options, "prev_word")
        pos = options.get("pos")
        pos_result = None
        if pos is not None:
            pos = self._text(options, "pos", 20)
            pos_result = engine.lemmatize_pos(form, pos, guess=guess, attested_only=attested_only)
        candidates = engine.lemmatize_verbose(form, previous, guess=guess,
                                              attested_only=attested_only,
                                              with_attestation=with_attestation)
        return {"form": form, "pos_result": pos_result, "candidates": candidates}

    def _evaluate_batch(self, options):
        words = self._text_list(options, "words", 500)
        engine = self._engine(options)
        guess = self._boolean(options, "guess", False)
        attested_only = self._boolean(options, "attested_only", False)
        tags = options.get("upos_tags")
        if tags is None:
            lemmas = engine.lemmatize_batch(words, guess=guess, attested_only=attested_only)
        else:
            tags = self._text_list(options, "upos_tags", 500)
            if len(tags) != len(words):
                raise ValueError("upos_tags must have the same length as words")
            lemmas = engine.lemmatize_batch_pos(words, tags, guess=guess,
                                                attested_only=attested_only)
        return [{"form": form, "lemma": lemma} for form, lemma in zip(words, lemmas)]

    def _evaluate_predict_pos(self, options):
        words = self._text_list(options, "words", 500)
        engine = self._engine(options)
        tags = engine.predict_pos_batch(words)
        return [{"form": form, "upos": tag} for form, tag in zip(words, tags)]

    def _evaluate_attestation(self, options):
        engine = self._engine(options)
        lemma = options.get("lemma")
        form = options.get("form")
        maximum = self._integer(options, "max_citations", 10, 0, 100)
        result = {}
        if lemma is not None:
            lemma = self._text(options, "lemma")
            result["lemma"] = engine.attestation(lemma)
        if form is not None:
            form = self._text(options, "form")
            result["form"] = engine.form_attestation(form, max_citations=maximum)
        if not result:
            raise ValueError("Supply lemma, form, or both")
        return result

    def _evaluate_spelling(self, options):
        engine = self._engine(options)
        form = self._text(options, "form")
        maximum = self._integer(options, "max_distance", 2, 0, 5)
        ocr_mode = self._boolean(options, "ocr_mode", False)
        headwords_only = self._choice(options, "headwords_only",
                                      (None, "lsj", "cunliffe", "wiktionary"), None)
        lemmata_only = self._boolean(options, "lemmata_only", False)
        return engine.suggest_spelling(form, maximum, ocr_mode,
                                       headwords_only, lemmata_only)

    def _evaluate_headwords(self, options):
        engine = self._engine(options)
        word = self._text(options, "word")
        convention = self._text(options, "headword_convention", 40,
                                default="lsj")
        end = options.get("end")
        result = {"word": word, "convention": convention,
                  "is_headword": engine.is_headword(word, convention)}
        if end is not None:
            end = self._text(options, "end")
            result["range"] = engine.headwords_between(word, end)
        return result

    def _evaluate_repair(self, options):
        engine = self._engine(options)
        lemma = self._text(options, "lemma")
        form = options.get("form")
        if form is not None:
            form = self._text(options, "form")
        return {"input": lemma, "form": form,
                "repaired": engine.repair_lemma(lemma, form=form)}

    def _evaluate_tagger(self, options):
        text = self._text(options, "text", 20000)
        segment = self._boolean(options, "segment_text", True)
        tagger = self._tagger(options)
        return {"on_gpu": tagger.on_gpu, "sentences": tagger.tag(text, segment_text=segment)}

    def _evaluate_paradigm(self, options):
        self._configure_environment()
        from dilemma import generate_paradigm
        lemma = self._text(options, "lemma")
        pos = self._choice(options, "pos", ("verb", "noun", "adj"), "verb")
        allow_template = self._boolean(options, "allow_template", True)
        attested_only = self._boolean(options, "attested_only", False)
        with_attestation = self._boolean(options, "with_attestation", True)
        maximum = self._integer(options, "max_citations", 3, 0, 20)
        return generate_paradigm(lemma, pos, lang="grc", allow_template=allow_template,
                                 attested_only=attested_only,
                                 with_attestation=with_attestation,
                                 max_citations=maximum)

    def _evaluate_generate(self, options):
        self._configure_environment()
        from dilemma import ParadigmSlot, generate
        lemma = self._text(options, "lemma")
        slot_value = options.get("slot")
        if not isinstance(slot_value, dict):
            raise ValueError("slot must be an object")
        allowed = {"pos", "voice", "tense", "mood", "person", "number", "case", "gender"}
        if not set(slot_value).issubset(allowed) or "pos" not in slot_value:
            raise ValueError("slot contains unsupported fields or lacks pos")
        slot = ParadigmSlot(**slot_value)
        allow_template = self._boolean(options, "allow_template", True)
        attested_only = self._boolean(options, "attested_only", False)
        with_attestation = self._boolean(options, "with_attestation", True)
        maximum = self._integer(options, "max_citations", 3, 0, 20)
        return generate(lemma, slot, lang="grc", allow_template=allow_template,
                        attested_only=attested_only,
                        with_attestation=with_attestation,
                        max_citations=maximum)

    def _evaluate_morphology_diff(self, options):
        self._configure_environment()
        from dilemma import diff_form, diff_paradigm
        lemma = self._text(options, "lemma")
        forms = options.get("forms")
        if forms is not None:
            if not isinstance(forms, dict) or not forms:
                raise ValueError("forms must be a nonempty object")
            if any(not isinstance(name, str) or not isinstance(form, str)
                   or not name or not form for name, form in forms.items()):
                raise ValueError("forms must map nonempty slot names to nonempty forms")
            return diff_paradigm(lemma, forms, lang="grc")
        form = self._text(options, "form")
        return diff_form(lemma, form, lang="grc")

    def _evaluate_reconcile(self, options):
        self._configure_environment()
        from dilemma import Reading, reconcile_token, vote_readings
        form = self._text(options, "form")
        raw_readings = options.get("readings")
        if not isinstance(raw_readings, list) or not raw_readings:
            raise ValueError("readings must be a nonempty array")
        readings = []
        for item in raw_readings:
            if not isinstance(item, dict):
                raise ValueError("each reading must be an object")
            source = item.get("source")
            lemma = item.get("lemma")
            upos = item.get("upos")
            feats = item.get("feats", {})
            if not isinstance(source, str) or not source:
                raise ValueError("each reading requires a source")
            if lemma is not None and not isinstance(lemma, str):
                raise ValueError("reading lemma must be text or null")
            if upos is not None and not isinstance(upos, str):
                raise ValueError("reading upos must be text or null")
            if not isinstance(feats, dict):
                raise ValueError("reading feats must be an object")
            readings.append(Reading(source=source, lemma=lemma, upos=upos, feats=feats))
        chosen, disagreements = vote_readings(readings)
        reconciled = reconcile_token(form, readings, meta=options.get("meta"))
        return {"vote": {"chosen": chosen, "disagreements": disagreements},
                "reconciled": reconciled}

    def _evaluate_normalization(self, options):
        self._configure_environment()
        from dilemma import grave_to_acute, strip_accents, to_monotonic
        from dilemma.form_sanitize import (canonicalize_final_elision, is_capitalized,
                                            nonlexical_generated_lemma,
                                            resolve_editorial_form, sanitize_form)
        text = self._text(options, "text")
        return {
            "original": text,
            "monotonic": to_monotonic(text),
            "grave_to_acute": grave_to_acute(text),
            "without_accents": strip_accents(text),
            "sanitized": sanitize_form(text),
            "editorial_forms": resolve_editorial_form(text),
            "canonical_elision": canonicalize_final_elision(text),
            "capitalized": is_capitalized(text),
            "generated_nonlexical": nonlexical_generated_lemma(text),
        }

    def _evaluate_nonlexical(self, options):
        self._configure_environment()
        from dilemma import classify_nonlexical, is_lexical
        forms = self._text_list(options, "forms", 500)
        return [{"form": form, "classification": classify_nonlexical(form),
                 "lexical": is_lexical(form)} for form in forms]

    def _evaluate_citation(self, options):
        self._configure_environment()
        from dilemma import trusted_ag_citation_headwords
        from dilemma.citation import malformed_tonal_reason
        lemmas = self._text_list(options, "lemmas", 500)
        engine = self._engine(options)
        return {
            "trusted_headword_count": len(trusted_ag_citation_headwords()),
            "lemmas": [{"lemma": lemma,
                        "tonal_issue": malformed_tonal_reason(lemma),
                        "status": engine.citation_status(lemma)}
                       for lemma in lemmas],
        }

    def _evaluate_lookup(self, options):
        self._configure_environment()
        from dilemma import LookupDB
        forms = self._text_list(options, "forms", 500)
        database = LookupDB(self.data / "lookup.db", lang="grc")
        database.enable_cache()
        return {"rows": len(database),
                "lookups": [{"form": form, "lemma": database.get(form),
                             "present": form in database} for form in forms]}

    def _evaluate_cache(self, options):
        engine = self._engine({**options, "skip_pos": True})
        forms = self._text_list(options, "forms", 500)
        engine.preload()
        cache = engine.export_cache()
        return {"entries": len(cache),
                "lookups": [{"form": form, "lemma": cache.get(form),
                             "present": form in cache} for form in forms]}

    def _evaluate_inventory(self, _options):
        self._configure_environment()
        import dilemma
        return {
            "package_version": dilemma.__version__,
            "exports": sorted(dilemma.__all__),
            "artifacts": self.artifact_metadata(),
            "paths": {"data": str(self.data), "model": str(self.model),
                      "tagger": str(self.tagger), "paradigm_data": str(self.paradigm_data)},
        }

    @staticmethod
    def _plain(value):
        if dataclasses.is_dataclass(value):
            return DilemmaProvider._plain(dataclasses.asdict(value))
        if isinstance(value, dict):
            return {str(name): DilemmaProvider._plain(item) for name, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [DilemmaProvider._plain(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if hasattr(value, "value"):
            return value.value
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return repr(value)

    @staticmethod
    def _text(options, name, maximum=10000, default=None):
        value = options.get(name, default)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"{name} must be nonempty text of at most {maximum} characters")
        return value.strip()

    @staticmethod
    def _text_list(options, name, maximum):
        values = options.get(name)
        if (not isinstance(values, list) or not 1 <= len(values) <= maximum
                or any(not isinstance(value, str) or not value.strip()
                       or len(value) > 10000 for value in values)):
            raise ValueError(f"{name} must contain 1 to {maximum} nonempty text values")
        return [value.strip() for value in values]

    @staticmethod
    def _boolean(options, name, default):
        value = options.get(name, default)
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
        return value

    @staticmethod
    def _integer(options, name, default, minimum, maximum):
        value = options.get(name, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
        return value

    @staticmethod
    def _choice(options, name, choices, default):
        value = options.get(name, default)
        if value not in choices:
            raise ValueError(f"{name} must be one of {choices}")
        return value

    def match_forms(self, lemma, forms):
        result = []
        artifacts = self.artifact_metadata()
        with read_index(self.data / "lookup.db") as db:
            for start in range(0, len(forms), 400):
                group = [key(form) for form in forms[start:start + 400]]
                if not group:
                    continue
                placeholders = ",".join("?" for _ in group)
                sql = ("SELECT lookup.form, lemmas.text, lookup.src, lookup.lang FROM lookup "
                       "JOIN lemmas ON lookup.lemma_id = lemmas.id "
                       f"WHERE lookup.form IN ({placeholders}) AND lemmas.text = ? "
                       "AND lookup.lang IN ('grc', 'all') ORDER BY lookup.form, lookup.src")
                for row in db.execute(sql, [*group, key(lemma)]):
                    result.append({
                        "evidence_type": "candidate_analysis", "provider": self.manifest["id"],
                        "provider_version": self.manifest["version"], "source": self.manifest["source"],
                        "license": self.manifest["license"], "artifacts": artifacts,
                        "form": row["form"], "lemma": row["text"], "method": "lookup",
                        "lookup_source": row["src"], "lookup_language": row["lang"],
                        "classification": "lookup_candidate",
                        "limitations": "Direct lookup rows only; inferred forms and other candidates may be missing.",
                    })
        return result

    def lemma_forms(self, lemma, limit):
        lemma = key(lemma)
        artifacts = self.artifact_metadata()
        with read_index(self.data / "lookup.db") as db:
            rows = db.execute(
                "SELECT DISTINCT lookup.form, lookup.src, lookup.lang FROM lookup "
                "JOIN lemmas ON lookup.lemma_id = lemmas.id "
                "WHERE lemmas.text = ? AND lookup.lang IN ('grc', 'all') "
                "ORDER BY lookup.form, lookup.src LIMIT ?",
                (lemma, limit + 1),
            ).fetchall()
        if len(rows) > limit:
            raise ValueError(f"Dilemma lemma form inventory exceeds {limit} records")
        return [{
            "evidence_type": "candidate_analysis",
            "provider": self.manifest["id"],
            "provider_version": self.manifest["version"],
            "source": self.manifest["source"],
            "license": self.manifest["license"],
            "artifacts": artifacts,
            "form": row["form"],
            "lemma": lemma,
            "method": "lookup",
            "lookup_source": row["src"],
            "lookup_language": row["lang"],
            "classification": "direct_lookup",
            "limitations": "Direct Dilemma lookup rows; related lemmas and generated forms are separate.",
        } for row in rows]


def create_provider(manifest, root):
    return DilemmaProvider(manifest, root)
