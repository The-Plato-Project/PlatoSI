import json
import contextlib
import io
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.registry import Registry
from platosi.cli import main
from platosi.unicode_search import key, matches


class UnicodeTests(unittest.TestCase):
    def test_normalization_and_boundaries(self):
        composed = "κατέβην"
        decomposed = unicodedata.normalize("NFD", composed)
        self.assertEqual(key(composed), key(decomposed))
        self.assertNotEqual(key(composed), key("κατεβην"))
        self.assertEqual(key(composed, "accent-insensitive"), key("κατεβην", "accent-insensitive"))
        self.assertNotEqual(key("ἄνθρωπος"), key("ἅνθρωπος"))
        self.assertEqual(key("ἄνθρωπος", "accent-insensitive"), key("ἅνθρωπος", "accent-insensitive"))
        self.assertNotEqual(key("Κατέβην"), key(composed))
        self.assertEqual(list(matches(key("κατέβην, κατέβηνα· κατέβην."), key(composed))), [(0, 7), (19, 26)])
        self.assertEqual(key("κατέβην \n  χθὲς"), "κατέβην χθὲς")

    def test_sqlite_default_fts5_is_not_greek_normalization(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE VIRTUAL TABLE f USING fts5(text)")
            db.execute("INSERT INTO f VALUES (?)", ("κατέβην",))
            def found(query):
                return db.execute("SELECT COUNT(*) FROM f WHERE f MATCH ?", ('"' + query + '"',)).fetchone()[0]
            self.assertEqual(found("κατέβην"), 1)
            self.assertEqual(found(unicodedata.normalize("NFD", "κατέβην")), 0)
            self.assertEqual(found("κατεβην"), 0)



# A synthetic capability fixture; no linguistic resource or parser is loaded.
MORPHOLOGY_FIXTURE = """
from pathlib import Path
from platosi.unicode_search import key

class Provider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.index = Path(root) / 'data' / 'indexes' / 'fixture-morphology.txt'
    def build(self):
        self.index.parent.mkdir(parents=True, exist_ok=True)
        self.index.write_text('synthetic fixture', encoding='utf-8')
    def available(self): return self.index.is_file()
    def analyze(self, form, mode, limit):
        if key(form, mode) != key('κατέβην', mode): return []
        return [{'provider': self.manifest['id'], 'provider_version': self.manifest['version'],
                 'source': self.manifest['source'], 'license': self.manifest['license'],
                 'evidence_type': 'candidate_analysis', 'classification': 'synthetic_fixture',
                 'form': form, 'lemma': 'καταβαίνω', 'tag': tag}
                for tag in ('fixture-reading-a', 'fixture-reading-b')][:limit]
    def match_forms(self, lemma, forms):
        return [record for form in forms for record in self.analyze(form, 'exact', 20)
                if key(record['lemma']) == key(lemma)]
    def lemma_forms(self, lemma, limit):
        return self.match_forms(lemma, ['κατέβην'])[:limit]

def create_provider(manifest, root): return Provider(manifest, root)
"""


class PluginFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "plugins", self.root / "plugins",
                        ignore=shutil.ignore_patterns("__pycache__", "ollama", "morpheus"))
        for manifest_path in (self.root / "plugins").glob("*/plugin.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["config"]["inventory"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        corpus = self.root / "data" / "tlg0059" / "tlg030"
        corpus.mkdir(parents=True)
        self.xml = corpus / "tlg0059.tlg030.perseus-grc2.xml"
        self.xml.write_text(
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><refsDecl n="CTS"/></teiHeader>'
            '<text><body xml:base="urn:cts:greekLit:tlg0059.tlg030.perseus-grc2">'
            '<div type="edition"><div type="textpart" subtype="book" n="1">'
            '<div type="textpart" subtype="section" n="327"><p>'
            '<milestone unit="section" resp="Stephanus" n="327a"/>'
            'κατέβην <hi>χθὲς</hi> εἰς Πειραιᾶ, κατέβηνα.'
            '</p></div><div type="textpart" subtype="section" n="328">'
            '<p>ἔδοξεν βουλόμενος καταλιπὼν <del>ψεῦδος</del></p></div></div></div></body></text></TEI>',
            encoding="utf-8")
        lsj = self.root / "data" / "lsj-logeion"
        lsj.mkdir(parents=True)
        (lsj / "greatscott02.xml").write_text(
            '<tei.2><text><div1><div2 id="duplicate"><head>καταβαίνω</head>'
            '<etym lang="grc">βαίνω</etym>first</div2>'
            '<div2 id="duplicate"><head>καταβαίνω</head>second</div2>'
            '<div2 id="base"><head>βαίνω</head>go</div2>'
            '<div2 id="distance"><head>πόρρω</head>'
            '<orth extent="suff">πόρρ-ωθεν</orth><orth extent="suff">-ος</orth>afar'
            '</div2></div1></text></tei.2>',
            encoding="utf-8")
        morphology = self.root / "plugins" / "fixture-morphology"
        morphology.mkdir()
        (morphology / "plugin.json").write_text(json.dumps({
            "id": "fixture-morphology", "type": "morphology", "version": "test",
            "module": "provider.py", "capabilities": ["analyze", "match_forms", "lemma_forms"],
            "enabled_by_default": False, "source": {"revision": "synthetic fixture"},
            "license": {"status": "test fixture"}, "config": {},
        }), encoding="utf-8")
        (morphology / "provider.py").write_text(MORPHOLOGY_FIXTURE, encoding="utf-8")
        self.registry = Registry(self.root)
        for r in self.registry.providers.values():
            r.load().build()

    def tearDown(self):
        self.temp.cleanup()

    def test_corpus_structure_original_and_citations(self):
        provider = self.registry.providers["perseus-plato"].load()
        results = provider.search("κατέβην χθὲς εἰς Πειραιᾶ", "exact", 10)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["evidence_type"], "primary_text")
        self.assertEqual(result["stephanus_at_match"]["section"], "327a")
        self.assertIn("1.327", [c["citation"] for c in result["citations"]])
        body = ET.parse(self.xml).getroot().find(".//{http://www.tei-c.org/ns/1.0}body")
        self.assertIn(result["text"], "".join(body.itertext()))
        self.assertEqual(result["text"][result["match_start"]:result["match_end"]], result["match"])
        self.assertEqual(len(provider.search("κατέβην", "exact", 10)), 1)
        self.assertEqual(len(provider.search("κατεβην", "exact", 10)), 0)
        self.assertEqual(len(provider.search("κατεβην", "accent-insensitive", 10)), 1)
        self.assertEqual(len(provider.search(unicodedata.normalize("NFD", "κατέβην"), "exact", 10)), 1)
        self.assertEqual(len(provider.passage(result["edition"], "1.327")), 1)
        self.assertEqual(len(provider.passage(result["edition"], "327a")), 1)
        self.assertEqual(len(provider.search("κατέβηνα.ἔδοξεν", "exact", 10)), 1)
        deleted = provider.search("ψεῦδος", "exact", 10)[0]
        self.assertEqual(deleted["evidence_type"], "editorial_text")
        self.assertTrue(any(m["tag"] == "del" for m in deleted["source_markup"]))

    def test_duplicate_ids_and_ambiguity(self):
        dictionary = self.registry.providers["lsj-logeion"].load()
        results = dictionary.lookup("καταβαίνω", "exact", 10)
        self.assertEqual(len(results), 2)
        self.assertEqual([r["entry_id"] for r in results], ["duplicate", "duplicate"])
        self.assertNotEqual(results[0]["entry_ordinal"], results[1]["entry_ordinal"])
        self.assertEqual(results[0]["evidence_type"], "scholarly_classification")
        relations = dictionary.lemma_relations("καταβαίνω", 10)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["target_lemma"], "βαίνω")
        self.assertEqual(relations[0]["relation_type"], "etymological_relation")
        self.assertEqual(relations[0]["classification"], "explicit_dictionary_markup")
        variant = dictionary.lookup("πόρρωθεν", "exact", 10)
        self.assertEqual(len(variant), 1)
        self.assertEqual(variant[0]["headword"], "πόρρω")
        self.assertEqual(variant[0]["matched_term"], "πόρρωθεν")
        self.assertEqual(variant[0]["match_kind"], "explicit_orthographic_variant")
        self.assertIn("πόρρ-ωθεν", variant[0]["match_fragment"])
        self.assertEqual(dictionary.lookup("ος", "exact", 10), [])
        morph = self.registry.providers["fixture-morphology"].load()
        analyses = morph.analyze("κατέβην", "exact", 10)
        self.assertEqual(len(analyses), 2)
        self.assertNotEqual(analyses[0]["tag"], analyses[1]["tag"])
        self.assertTrue(all(r["evidence_type"] == "candidate_analysis" for r in analyses))

    def test_disable_remove_and_multiple_providers(self):
        self.assertFalse(self.registry.providers["fixture-morphology"].enabled)
        self.assertEqual(list(self.registry.active("analyze")), [])
        self.registry.set_enabled("fixture-morphology", True)
        self.assertEqual(len(list(self.registry.active("analyze"))), 1)
        self.registry.set_enabled("fixture-morphology", False)
        dictionary = list(self.registry.active("lookup"))
        self.assertEqual(len(dictionary), 1)
        self.assertEqual(len(dictionary[0][1].lookup("καταβαίνω", "exact", 10)), 2)
        self.registry.set_enabled("lsj-logeion", False)
        self.assertEqual(len(list(self.registry.active("lookup"))), 0)
        active = list(self.registry.active("search"))
        self.assertEqual(len(active), 1)
        self.assertTrue(active[0][1].search("κατέβην", "exact", 1))
        (self.root / "plugins" / "fixture-morphology" / "plugin.json").unlink()
        second = self.root / "plugins" / "second-corpus"
        shutil.copytree(self.root / "plugins" / "perseus-plato", second, ignore=shutil.ignore_patterns("__pycache__"))
        manifest_path = second / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = "second-corpus"
        manifest["config"]["index"] = "data/indexes/second.sqlite"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        registry = Registry(self.root)
        registry.providers["second-corpus"].load().build()
        active = list(registry.active("search"))
        self.assertEqual(len(active), 2)
        self.assertEqual({provider.search("κατέβην", "exact", 1)[0]["provider"]
                          for _, provider in active}, {"perseus-plato", "second-corpus"})
        self.assertEqual(len(list(registry.active("analyze"))), 0)
        self.assertEqual(len(list(registry.active("lookup"))), 0)
        other_index = registry.providers["second-corpus"].load().index
        before = other_index.read_bytes()
        registry.providers["perseus-plato"].load().build()
        self.assertEqual(before, other_index.read_bytes())

    def test_missing_index_and_failed_rebuild(self):
        registration = self.registry.providers["lsj-logeion"]
        provider = registration.load()
        before = provider.index.read_bytes()
        (provider.source / "greatscott02.xml").write_text("<invalid", encoding="utf-8")
        with self.assertRaises(ET.ParseError):
            provider.build()
        self.assertEqual(before, provider.index.read_bytes())
        registration.manifest["version"] = "2.0"
        self.assertFalse(provider.available())
        provider.index.unlink()
        self.assertFalse(provider.available())
        self.assertEqual(list(self.registry.active("lookup")), [])

    def test_independent_minimal_provider_and_removal(self):
        indexes = [self.registry.providers[name].load().index
                   for name in ("perseus-plato", "lsj-logeion", "fixture-morphology")]
        before = {path: path.read_bytes() for path in indexes}
        plugin = self.root / "plugins" / "independent-test"
        plugin.mkdir()
        (plugin / "plugin.json").write_text(json.dumps({
            "id": "independent-test", "type": "corpus", "version": "1",
            "module": "provider.py", "capabilities": ["search"],
            "source": {"revision": "fixture"}, "license": {"status": "test fixture"}
        }), encoding="utf-8")
        (plugin / "provider.py").write_text(
            "class Provider:\n"
            "    def available(self): return True\n"
            "    def search(self, query, mode, limit):\n"
            "        return [{'provider': 'independent-test', 'query': query}]\n"
            "def create_provider(manifest, root): return Provider()\n",
            encoding="utf-8")
        registry = Registry(self.root)
        active = dict((registration.manifest["id"], provider)
                      for registration, provider in registry.active("search"))
        self.assertEqual(active["independent-test"].search("test", "exact", 1)[0]["query"], "test")
        self.assertTrue(active["perseus-plato"].search("κατέβην", "exact", 1))
        shutil.rmtree(plugin)
        registry = Registry(self.root)
        self.assertNotIn("independent-test", registry.providers)
        self.assertTrue(registry.providers["perseus-plato"].load().search("κατέβην", "exact", 1))
        self.assertTrue(registry.providers["lsj-logeion"].load().lookup("καταβαίνω", "exact", 1))
        self.assertEqual(before, {path: path.read_bytes() for path in indexes})

    def test_cli_reports_missing_provider(self):
        def analyze():
            output = io.StringIO()
            with patch.object(sys, "argv", ["platosi", "--root", str(self.root), "analyze", "κατέβην"]):
                with contextlib.redirect_stdout(output):
                    main()
            return json.loads(output.getvalue())

        result = analyze()
        self.assertEqual(result["available_providers"], [])
        self.assertEqual(result["results"], [])
        self.assertIn("No enabled and available provider", result["message"])
        self.assertFalse(next(p for p in result["providers"] if p["id"] == "fixture-morphology")["enabled"])
        self.registry.set_enabled("fixture-morphology", True)
        result = analyze()
        self.assertEqual(result["available_providers"], ["fixture-morphology"])
        self.assertNotIn("message", result)
        self.registry.providers["fixture-morphology"].load().index.unlink()
        result = analyze()
        self.assertEqual(result["results"], [])
        self.assertIn("No enabled and available provider", result["message"])
        self.assertFalse(next(p for p in result["providers"] if p["id"] == "fixture-morphology")["available"])
        (self.root / "plugins" / "fixture-morphology" / "plugin.json").unlink()
        result = analyze()
        self.assertEqual(result["available_providers"], [])
        self.assertIn("No enabled and available provider", result["message"])
        self.assertFalse(any(p["id"] == "fixture-morphology" for p in result["providers"]))


class RealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = Registry(ROOT)
        cls.corpus = cls.registry.providers["perseus-plato"].load()
        cls.dictionary = cls.registry.providers["lsj-logeion"].load()
        if not cls.corpus.available() or not cls.dictionary.available():
            raise unittest.SkipTest("Real corpus and dictionary indexes not built")

    def test_samples_against_xml(self):
        for word in ("κατέβην", "βουλόμενος", "ἔδοξεν", "καταλιπὼν"):
            with self.subTest(word=word):
                matches_found = self.corpus.search(word, "exact", 1)
                self.assertTrue(matches_found)
                result = matches_found[0]
                body = ET.parse(result["source_path"]).getroot().find(".//{http://www.tei-c.org/ns/1.0}body")
                self.assertIn(result["text"], "".join(body.itertext()))
                self.assertEqual(result["match"], word)
                self.assertEqual(result["evidence_type"], "primary_text")
                self.assertTrue(result["source"]["revision"])
        results = self.corpus.search("κατέβην χθὲς εἰς Πειραιᾶ", "exact", 10)
        republic = next(r for r in results if ".tlg030." in r["edition"])
        self.assertEqual(republic["stephanus_at_match"]["section"], "327a")
        self.assertIn("1.327", [r["citation"] for r in republic["citations"]])
        body = ET.parse(republic["source_path"]).getroot().find(".//{http://www.tei-c.org/ns/1.0}body")
        self.assertIn(republic["text"], "".join(body.itertext()))

    def test_real_dictionary(self):
        entries = self.dictionary.lookup("καταβαίνω", "exact", 20)
        self.assertTrue(entries)
        entry = entries[0]
        source = ET.parse(entry["source_path"]).getroot()
        original = source.findall("./text/div1/div2")[entry["entry_ordinal"] - 1]
        self.assertEqual(original.get("id"), entry["entry_id"])
        self.assertEqual("".join(original.find("head").itertext()), entry["headword"])
        duplicate = [r for r in self.dictionary.lookup("ἕως", "exact", 100) if r["entry_id"] == "crosse(/ws"]
        self.assertEqual(len(duplicate), 2)
        self.assertNotEqual((duplicate[0]["source_path"], duplicate[0]["entry_ordinal"]),
                            (duplicate[1]["source_path"], duplicate[1]["entry_ordinal"]))



if __name__ == "__main__":
    unittest.main()
