import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.canonical_build import extract_segments
from platosi.canonical_text import CanonicalCorpus, DATA, LocationError, make_work, segment_digest
from platosi.dialogue_morphology import DialogueMorphologyIndex
from platosi.reader_api import InvalidRequest, ReaderApi


class CanonicalTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = json.loads((ROOT / "tests" / "fixtures" / "text-location-v1.json").read_text(encoding="utf-8"))
        segments = []
        for section in self.fixture["sections"]:
            for text in section["segments"]:
                segments.append({"stephanus": section["stephanus"], "division": {"type": "book", "label": "1"},
                                 "text": text, "annotations": []})
        entry = {"dialogue": self.fixture["dialogue"], "tlg": "tlg030", "edition": "perseus-grc2",
                 "title": "Fixture", "title_greek": None, "text_version": self.fixture["text_version"],
                 "segments_sha256": segment_digest(segments)}
        inventory = {"contract": self.fixture["contract"], "source_repository": "fixture",
                     "source_revision": "fixture-revision", "works": [entry]}
        inventory_path = self.root / "docs" / "canonical-corpus-v1-inventory.json"
        inventory_path.parent.mkdir(parents=True)
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        self.work_path = self.root / DATA / "works" / "fixture-dialogue.json"
        self.work_path.parent.mkdir(parents=True)
        self.work_path.write_text(json.dumps(make_work(inventory, entry, segments), ensure_ascii=False), encoding="utf-8")
        self.corpus = CanonicalCorpus(self.root)
        self.api = ReaderApi(self.root)

    def location(self, case):
        return {"dialogue": case.get("dialogue", self.fixture["dialogue"]),
                "text_version": case.get("text_version", self.fixture["text_version"]),
                "start": {"stephanus": case["start"][0], "offset": case["start"][1]},
                "end": {"stephanus": case["end"][0], "offset": case["end"][1]}}

    def test_shared_location_vectors_against_production(self):
        for case in self.fixture["valid"]:
            with self.subTest(case=case["name"]):
                result = self.corpus.resolve(self.location(case))
                self.assertEqual(result["text"], case["text"])
                self.assertEqual(result["location"], self.location(case))
        for case in self.fixture["invalid"]:
            with self.subTest(case=case["name"]):
                expected = "VERSION_UNAVAILABLE" if case["error"] == "VERSION_MISMATCH" else case["error"]
                with self.assertRaisesRegex(LocationError, "^" + expected + ":"):
                    self.corpus.resolve(self.location(case))

    def test_catalogue_work_division_and_location_api(self):
        capabilities = self.api.execute("capabilities", {})["capabilities"]
        self.assertTrue(next(item for item in capabilities if item["operation"] == "canonical.resolve")["available"])
        catalogue = self.api.execute("canonical.catalog", {})
        self.assertEqual(catalogue["works"][0]["text_version"], self.fixture["text_version"])
        work = self.api.execute("canonical.work", {"dialogue": "fixture-dialogue",
                                                  "division": {"type": "book", "label": "1"}})
        self.assertEqual(len(work["sections"]), 3)
        self.assertEqual(work["source"]["revision"], "fixture-revision")
        result = self.api.execute("canonical.resolve", {"location": self.location(self.fixture["valid"][2])})
        self.assertEqual(result["text"], self.fixture["valid"][2]["text"])
        self.assertEqual([item["stephanus"] for item in result["context"]], ["327a", "327b"])
        with self.assertRaisesRegex(InvalidRequest, "Unknown dialogue division"):
            self.api.execute("canonical.work", {"dialogue": "fixture-dialogue",
                                               "division": {"type": "book", "label": "2"}})
        with self.assertRaisesRegex(InvalidRequest, "INVALID_LOCATION"):
            self.api.execute("canonical.resolve", {"location": {}})
        with self.assertRaisesRegex(InvalidRequest, "only a location"):
            self.api.execute("canonical.resolve", {"location": self.location(self.fixture["valid"][0]),
                                                   "text": "κατέβην"})
        invalid = self.location(self.fixture["valid"][0])
        invalid["text"] = "κατέβην"
        with self.assertRaisesRegex(InvalidRequest, "INVALID_LOCATION"):
            self.api.execute("canonical.resolve", {"location": invalid})

    def test_missing_and_modified_corpus_report_errors(self):
        self.work_path.unlink()
        self.assertFalse(self.corpus.available())
        with self.assertRaisesRegex(FileNotFoundError, "incomplete"):
            self.corpus.catalogue()
        with self.assertRaisesRegex(FileNotFoundError, "unavailable"):
            self.corpus.work("fixture-dialogue")

    def test_partial_install_reports_available_operations(self):
        path = self.root / "docs" / "canonical-corpus-v1-inventory.json"
        inventory = json.loads(path.read_text(encoding="utf-8"))
        inventory["works"].append({**inventory["works"][0], "dialogue": "missing"})
        path.write_text(json.dumps(inventory), encoding="utf-8")
        capabilities = {item["operation"]: item["available"] for item in self.api.execute("capabilities", {})["capabilities"]}
        self.assertFalse(capabilities["canonical.catalog"])
        self.assertTrue(capabilities["canonical.work"])
        self.assertTrue(capabilities["canonical.resolve"])
        self.assertEqual(self.api.execute("canonical.work", {"dialogue": "fixture-dialogue"})["dialogue"],
                         "fixture-dialogue")

    def test_tampering_is_not_silently_served(self):
        work = json.loads(self.work_path.read_text(encoding="utf-8"))
        work["sections"][0]["segments"][0]["text"] += "!"
        self.work_path.write_text(json.dumps(work, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "frozen baseline"):
            self.corpus.work("fixture-dialogue")

    def test_wrong_version_and_invalid_boundaries(self):
        with self.assertRaisesRegex(LocationError, "VERSION_UNAVAILABLE"):
            self.corpus.work("fixture-dialogue", "sha256:missing")
        location = self.location(self.fixture["valid"][0])
        location["end"]["offset"] = True
        with self.assertRaisesRegex(LocationError, "INVALID_OFFSET"):
            self.corpus.resolve(location)

    def test_canonical_text_does_not_require_other_providers(self):
        broken_plugin = self.root / "plugins" / "broken"
        broken_plugin.mkdir(parents=True)
        (broken_plugin / "plugin.json").write_text("{}", encoding="utf-8")
        result = self.api.execute("canonical.resolve", {"location": self.location(self.fixture["valid"][0])})
        self.assertEqual(result["text"], "κατέβην")

    def test_linguistic_evidence_uses_canonical_location_and_organizes_provider_data(self):
        plugin = self.root / "plugins" / "fixture-morphology"
        plugin.mkdir(parents=True)
        manifest = {
            "id": "fixture-morphology", "type": "morphology", "version": "1", "module": "provider.py",
            "capabilities": ["analyze", "lookup", "lemma_forms", "lemma_relations"],
            "enabled_by_default": True,
            "source": {"attribution": "fixture", "revision": "fixture"},
            "license": {"status": "test"}, "config": {},
        }
        (plugin / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (plugin / "provider.py").write_text(
            """
class Provider:
    def __init__(self, manifest):
        self.manifest = manifest
        self.lemma_forms_calls = 0
        self.metadata_calls = 0
    def available(self): return True
    def artifact_metadata(self):
        self.metadata_calls += 1
        return {'file_count': self.metadata_calls, 'total_bytes': 2}
    def artifact_metadata_for(self, capability):
        return {'capability': capability, 'revision': 'fixture'}
    def analyze(self, form, mode, limit):
        lemma = 'πέμπω' if form == 'ἔπεμπον' else 'καταβαίνω' if form == 'κατέβην' else None
        if lemma is None: return []
        return [
            {'provider': 'fixture-morphology', 'provider_version': '1',
             'source': self.manifest['source'], 'license': self.manifest['license'],
             'form': form, 'lemma': lemma, 'method': 'lookup',
             'classification': 'lookup_candidate',
             'settings': {'resolve_articles': False, 'guess': False},
             'analysis': {'lang': 'grc', 'headword': lemma, 'homograph': None,
                          'proper': False, 'score': 1,
                          'via': 'exact', 'tag': '', 'citation': 'unchanged'}},
            {'provider': 'fixture-morphology', 'provider_version': '1',
             'source': self.manifest['source'], 'license': self.manifest['license'],
             'form': form, 'lemma': lemma, 'method': 'lookup',
             'classification': 'lookup_candidate',
             'settings': {'resolve_articles': True, 'guess': False},
             'analysis': {'lang': 'grc', 'headword': lemma, 'homograph': None,
                          'proper': False, 'score': 1,
                          'via': 'exact', 'tag': '', 'citation': 'unchanged'}},
        ]
    def analyze_complete(self, form): return self.analyze(form, 'exact', 100)
    def index_identity(self):
        return {'provider': 'fixture-morphology', 'version': '1', 'policy': 'fixture'}
    def lookup(self, query, mode, limit):
        if query not in ('καταβαίνω', 'πέμπω'): return []
        definition = 'go down' if query == 'καταβαίνω' else 'send'
        return [{'provider': 'fixture-morphology', 'provider_version': '1',
                 'source': self.manifest['source'], 'license': self.manifest['license'],
                 'headword': query, 'matched_term': query, 'entry_id': 'entry',
                 'entry_xml': '<div2><head>' + query + '</head><sense>' + definition + '</sense></div2>'}]
    def lemma_forms(self, lemma, limit):
        self.lemma_forms_calls += 1
        if lemma == 'πέμπω':
            return [
                {'provider': 'fixture-morphology', 'provider_version': '1',
                 'source': self.manifest['source'], 'license': self.manifest['license'],
                 'form': 'ἔπεμπον', 'lemma': lemma, 'method': 'lookup',
                 'classification': 'direct_lookup'},
            ]
        return [
            {'provider': 'fixture-morphology', 'provider_version': '1',
             'source': self.manifest['source'], 'license': self.manifest['license'],
             'form': 'κατέβην', 'lemma': lemma, 'method': 'lookup',
             'classification': 'direct_lookup'},
            {'provider': 'fixture-morphology', 'provider_version': '1',
             'source': self.manifest['source'], 'license': self.manifest['license'],
             'form': 'καταβαίνει', 'lemma': lemma, 'method': 'lookup',
             'classification': 'direct_lookup'},
        ]
    def lemma_relations(self, lemma, limit):
        if lemma != 'καταβαίνω': return []
        return [
            {'provider': 'fixture-morphology', 'provider_version': '1',
             'source': self.manifest['source'], 'license': self.manifest['license'],
             'source_lemma': lemma, 'target_lemma': 'πέμπω',
             'relation_type': 'etymological_relation', 'direction': 'directed',
             'classification': 'explicit_dictionary_markup',
             'source_fragment': '<etym lang="grc">πέμπω</etym>'},
        ]
def create_provider(manifest, root): return Provider(manifest)
""", encoding="utf-8")
        api = ReaderApi(self.root)
        self.addCleanup(api.close)
        result = api.execute("linguistics.evidence",
                             {"location": self.location(self.fixture["valid"][0])})
        self.assertEqual(result["contract"], "platosi.linguistic-evidence.v1")
        self.assertEqual(result["target"]["text"], "κατέβην")
        self.assertEqual(result["possibilities"][0]["lemma"], "καταβαίνω")
        self.assertEqual(len(result["possibilities"][0]["candidates"]), 1)
        self.assertEqual(
            result["possibilities"][0]["candidates"][0]["supporting_settings"],
            [
                {"resolve_articles": False, "guess": False},
                {"resolve_articles": True, "guess": False},
            ],
        )
        self.assertEqual(result["dictionary"]["entries"][0]["plain_text"], "καταβαίνω go down")
        provider = api._current_registry.providers["fixture-morphology"].load()
        DialogueMorphologyIndex(self.root).build(
            api._current_registry, self.fixture["dialogue"], self.fixture["text_version"],
            provider_id="fixture-morphology",
        )
        dialogue = api.execute("linguistics.dialogue-lexicon",
                               {"location": self.location(self.fixture["valid"][0])})
        self.assertEqual(dialogue["contract"], "platosi.dialogue-lexicon.v1")
        self.assertEqual(dialogue["lemmas"][0]["lemma"], "καταβαίνω")
        self.assertEqual(dialogue["dictionary"]["entries"][0]["plain_text"], "καταβαίνω go down")
        self.assertEqual(dialogue["morphology"]["status"], "not_requested")
        self.assertEqual(dialogue["lemmas"][0]["forms"][0]["form"], "κατέβην")
        self.assertEqual(dialogue["lemmas"][0]["forms"][0]["count"], 1)
        lemma_forms_calls = provider.lemma_forms_calls
        cached_dialogue = api.execute(
            "linguistics.dialogue-lexicon",
            {"location": self.location(self.fixture["valid"][0])},
        )
        self.assertTrue(cached_dialogue["lemmas"][0]["cache"]["forms_hit"])
        self.assertEqual(provider.lemma_forms_calls, lemma_forms_calls)
        self.assertEqual(dialogue["lemmas"][0]["forms"][0]["occurrences"][0]["location"],
                         self.location(self.fixture["valid"][0]))
        related = dialogue["lemmas"][0]["related_lemmas"]
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["lemma"], "πέμπω")
        self.assertEqual(related[0]["dictionary"]["status"], "ok")
        self.assertEqual(related[0]["dictionary"]["entries"][0]["plain_text"], "πέμπω send")
        self.assertTrue(related[0]["present_in_dialogue"])
        self.assertEqual(related[0]["count"], 1)
        self.assertEqual(related[0]["forms"][0]["form"], "ἔπεμπον")
        cached = api.execute("linguistics.dialogue-lexicon",
                             {"location": self.location(self.fixture["valid"][0])})
        self.assertTrue(cached["lemmas"][0]["cache"]["forms_hit"])
        self.assertTrue(cached["lemmas"][0]["cache"]["relations_hit"])
        with self.assertRaisesRegex(InvalidRequest, "exactly one Greek word"):
            api.execute("linguistics.evidence",
                        {"location": self.location(self.fixture["valid"][2])})

    def test_tei_extraction_preserves_citation_paragraphs_and_verse(self):
        source = self.root / "test.xml"
        source.write_text(
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
            '<div subtype="book" n="1"><p><milestone unit="section" resp="Stephanus" n="327a"/>'
            'κατέβην <hi>χθὲς</hi><milestone unit="para"/>'
            'ἄλλος <cit><quote><l>πρῶτον</l><l>δεύτερον</l></quote>'
            '<bibl>source</bibl></cit> τέλος</p></div></body></text></TEI>',
            encoding="utf-8")
        segments = extract_segments(source)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["text"], "κατέβην χθὲς")
        self.assertEqual(segments[1]["text"], "ἄλλος\nπρῶτον\nδεύτερον\nsource\nτέλος")
        for annotation in segments[1]["annotations"]:
            text = segments[1]["text"]
            selected = text.encode("utf-16-le")[annotation["start"] * 2:annotation["end"] * 2].decode("utf-16-le")
            self.assertEqual(selected, "πρῶτον\nδεύτερον" if annotation["kind"] == "quotation" else "source")


if __name__ == "__main__":
    unittest.main()
