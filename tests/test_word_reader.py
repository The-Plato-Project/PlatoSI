import copy
import dataclasses
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.cancellation import Cancellation
from platosi.profiles import Profiles
from platosi.registry import Registry
from platosi.word_models import Examination, parse_assessment
from platosi.word_reader import WordReader, tokens
import test_retrieval


ALT = """
class Provider:
    def __init__(self, manifest, root): self.manifest = manifest
    def available(self): return True
    def analyze(self, form, mode, limit):
        lemma = 'ἕτερος' if form == 'κατέβην' else 'αὐτοῦ'
        return [{'provider': self.manifest['id'], 'evidence_type': 'candidate_analysis',
                 'form': form, 'lemma': lemma, 'source': {'revision': 'test'},
                 'classification': 'rule_generated_suggestion'}]
    def match_forms(self, lemma, forms):
        return [{'provider': self.manifest['id'], 'form': 'κατέβην', 'lemma': lemma,
                 'evidence_type': 'candidate_analysis'}] if lemma == 'ἕτερος' else []
def create_provider(manifest, root): return Provider(manifest, root)
"""


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_retrieval.PluginFixtureTests("test_duplicate_ids_and_ambiguity")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.fixture.registry.set_enabled("glem", True)
        folder = self.root / "plugins" / "alternate"
        folder.mkdir()
        (folder / "plugin.json").write_text(json.dumps({
            "id": "alternate", "type": "morphology", "version": "1", "module": "provider.py",
            "capabilities": ["analyze", "match_forms"], "source": {"revision": "test"},
            "license": {"status": "test"}, "config": {}}), encoding="utf-8")
        (folder / "provider.py").write_text(ALT, encoding="utf-8")
        self.reader = WordReader(self.root)
        self.query = {"corpus": "perseus-plato",
                      "edition": "urn:cts:greekLit:tlg0059.tlg030.perseus-grc2", "scope": "1"}
        self.scope = self.reader.scope(**{"provider_id": self.query["corpus"],
                                         "edition": self.query["edition"], "scope": "1"})
        self.query["start"] = next(t["start"] for t in tokens(self.scope["text"]) if t["form"] == "κατέβην")

    def test_competing_candidates_attribution_and_source_occurrences(self):
        with patch("socket.create_connection", side_effect=AssertionError("network used")):
            result = self.reader.explore(self.query)
            self.assertEqual(result["word"]["form"], "κατέβην")
            self.assertEqual(result["word"]["citation"]["section"], "327a")
            self.assertEqual({a["lemma"] for a in result["analyses"]}, {"καταβαίνω", "ἕτερος"})
            self.assertEqual(sum(a["provider"] == "glem" for a in result["analyses"]), 2)
            self.assertEqual(len(result["entries"]), 2)
            self.assertTrue(all(a["source"] for a in result["analyses"]))
            found = self.reader.occurrences({**self.query, "lemma": "καταβαίνω"})
        self.assertEqual([o["form"] for o in found["results"]], ["κατέβην"])
        occurrence = found["results"][0]
        self.assertEqual(self.scope["text"][occurrence["start"]:occurrence["end"]], occurrence["form"])
        self.assertEqual(occurrence["citation"]["section"], "327a")
        self.assertEqual({a["provider"] for a in occurrence["analyses"]}, {"glem"})
        self.assertIn("incomplete", found["limitations"])
        self.assertFalse(self.reader.occurrences({**self.query, "lemma": "ἀναβαίνω"})["results"])

    def test_profile_explicit_empty_resources_and_provider_failure(self):
        Profiles(self.root).save("text", ["glem", "lsj-logeion"], True)
        result = self.reader.explore({**self.query, "profile": "text"})
        self.assertEqual(result["analyses"], [])
        result = self.reader.explore({**self.query, "profile": "text", "include": ["glem"]})
        self.assertEqual(len(result["analyses"]), 2)
        self.assertEqual(self.reader.explore({**self.query, "include": []})["analyses"], [])
        (self.root / "plugins" / "alternate" / "provider.py").write_text(
            ALT.replace("lemma = 'ἕτερος'", "raise ValueError('bad analyzer')\n        lemma = 'ἕτερος'"),
            encoding="utf-8")
        self.reader = WordReader(self.root)
        result = self.reader.explore(self.query)
        self.assertEqual(len(result["analyses"]), 2)
        self.assertTrue(any("bad analyzer" in warning for warning in result["warnings"]))
        self.assertTrue(result["entries"])

    def test_invalid_position_is_rejected(self):
        with self.assertRaises(ValueError):
            self.reader.explore({**self.query, "start": self.query["start"] + 1})


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.examination = Examination(self.temp.name)
        self.local = {"word": {"evidence_type": "primary_text", "form": "κατέβην"},
                      "analyses": [{"evidence_type": "candidate_analysis", "lemma": "καταβαίνω"},
                                   {"evidence_type": "candidate_analysis", "lemma": "ἕτερος"}],
                      "entries": [], "limitations": "Provisional"}
        self.choices = {"primary": {"provider": "one", "model": "a"},
                        "validation": {"provider": "two", "model": "b"}}
        self.settings = {"temperature": 0.2, "max_tokens": 1024}
        self.messages = []
        test = self

        class Registration:
            def __init__(self, name):
                self.manifest = {"id": name, "version": "1", "config": {"secret": "not-for-cache"}}

        class Model:
            def __init__(self, name): self.name = name
            def list_models(self):
                return [{"name": "a" if self.name == "one" else "b", "digest": "digest-" + self.name}]
            def chat(self, messages, options, cancellation):
                test.messages.append(copy.deepcopy(messages))
                status = "plausible" if self.name == "one" else "uncertain"
                return {"text": json.dumps({"assessments": [
                    {"lemma": lemma, "status": status, "reason": "Evidence", "evidence_ids": ["E1"]}
                    for lemma in ("καταβαίνω", "ἕτερος")]})}

        def provider(registry, name, capability):
            return Registration(name), Model(name)

        self.provider = provider

    def test_independent_assessments_cache_and_fresh(self):
        with patch("platosi.word_models.model_provider", self.provider):
            result = self.examination.run(None, self.local, self.choices, self.settings, False, Cancellation())
            self.assertEqual(self.messages[0], self.messages[1])
            self.assertEqual(len(self.messages), 2)
            self.assertEqual(result["comparison"][0]["comparison"], "disagreement")
            self.assertTrue(self.examination.run(None, self.local, self.choices, self.settings, False, Cancellation())["cached"])
            self.assertEqual(len(self.messages), 2)
            self.examination.run(None, self.local, self.choices, self.settings, True, Cancellation())
            self.assertEqual(len(self.messages), 4)
            changed = copy.deepcopy(self.local)
            changed["word"]["form"] = "καταβαίνων"
            self.examination.run(None, changed, self.choices, self.settings, False, Cancellation())
            self.assertEqual(len(self.messages), 6)
        self.assertNotIn(b"not-for-cache", self.examination.path.read_bytes())

    def test_failure_is_isolated_and_not_cached(self):
        def one_down(registry, name, capability):
            if name == "one":
                raise OSError("offline")
            return self.provider(registry, name, capability)
        with patch("platosi.word_models.model_provider", one_down):
            result = self.examination.run(None, self.local, self.choices, self.settings, False, Cancellation())
        self.assertIn("offline", result["primary"]["error"])
        self.assertIn("assessments", result["validation"])
        self.assertFalse(self.examination.path.exists())

    def test_invalid_and_incomplete_assessments_rejected(self):
        package = {"evidence": [{"id": "E1", "record": self.local["analyses"][0]}]}
        for item in ({"lemma": [], "status": "plausible", "reason": "x", "evidence_ids": ["E1"]},
                     {"lemma": "καταβαίνω", "status": "plausible", "reason": "x", "evidence_ids": [{}]}):
            with self.assertRaises(ValueError):
                parse_assessment(json.dumps({"assessments": [item]}), package)
        with self.assertRaises(ValueError):
            parse_assessment('{"assessments":[]}', package)

class DilemmaThreadTests(unittest.TestCase):
    def test_analysis_reuses_sqlite_on_one_worker_thread(self):
        registration = Registry(ROOT).providers["dilemma"]
        provider = registration.load()
        @dataclasses.dataclass
        class Candidate:
            lemma: str
            source: str
        class Engine:
            def __init__(self, lemma, source):
                self.connection = sqlite3.connect(":memory:")
                self.lemma = lemma
                self.source = source
            def lemmatize_verbose(self, form, guess):
                self.connection.execute("SELECT 1")
                return [Candidate(self.lemma, self.source)]
        def initialize():
            if provider.engines is None:
                provider.engines = [Engine("αὐτοῦ", "lookup"), Engine("αὐτός", "article")]
            return provider.engines
        provider._engines = initialize
        results, errors = [], []
        def analyze():
            try:
                results.append(provider.analyze("αὐτοῦ", "exact", 100))
            except Exception as error:
                errors.append(error)
        first = threading.Thread(target=analyze)
        second = threading.Thread(target=analyze)
        first.start(); first.join(); second.start(); second.join()
        provider.worker.shutdown()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual({row["lemma"] for row in results[0]}, {"αὐτοῦ", "αὐτός"})
        self.assertEqual({row["settings"]["resolve_articles"] for row in results[0]}, {True, False})
        self.assertEqual({row["classification"] for row in results[0]},
                         {"lookup_candidate", "rule_generated_suggestion"})


if __name__ == "__main__":
    unittest.main()
