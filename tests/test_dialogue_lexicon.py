import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.canonical_text import DATA, make_work, segment_digest
from platosi.dialogue_lexicon import DialogueLexiconIndex


class DialogueLexiconIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "text-location-v1.json").read_text(encoding="utf-8")
        )
        segments = []
        for section in fixture["sections"]:
            for text in section["segments"]:
                segments.append({
                    "stephanus": section["stephanus"],
                    "division": {"type": "book", "label": "1"},
                    "text": text,
                    "annotations": [],
                })
        entry = {
            "dialogue": fixture["dialogue"],
            "tlg": "tlg030",
            "edition": "perseus-grc2",
            "title": "Fixture",
            "title_greek": None,
            "text_version": fixture["text_version"],
            "segments_sha256": segment_digest(segments),
        }
        inventory = {
            "contract": fixture["contract"],
            "source_repository": "fixture",
            "source_revision": "fixture-revision",
            "works": [entry],
        }
        inventory_path = self.root / "docs" / "canonical-corpus-v1-inventory.json"
        inventory_path.parent.mkdir(parents=True)
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        work_path = self.root / DATA / "works" / "fixture-dialogue.json"
        work_path.parent.mkdir(parents=True)
        work_path.write_text(
            json.dumps(make_work(inventory, entry, segments), ensure_ascii=False),
            encoding="utf-8",
        )
        self.dialogue = fixture["dialogue"]
        self.version = fixture["text_version"]
        self.index = DialogueLexiconIndex(self.root)

    def test_builds_once_and_counts_exact_surface_forms(self):
        first = self.index.ensure_dialogue(self.dialogue, self.version)
        second = self.index.ensure_dialogue(self.dialogue, self.version)
        self.assertEqual(first, second)
        counts = {item["form"]: item["count"] for item in self.index.form_counts(
            self.dialogue, self.version
        )}
        self.assertEqual(counts["κατέβην"], 1)
        self.assertEqual(counts["ἔπεμπον"], 1)
        self.assertNotIn("🏛", counts)
        self.assertEqual(sum(counts.values()), 7)

    def test_occurrences_use_canonical_utf16_locations(self):
        results = self.index.occurrences(self.dialogue, self.version, ["ἔπεμπον"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["location"]["start"], {"stephanus": "327b", "offset": 9})
        self.assertEqual(results[0]["location"]["end"], {"stephanus": "327b", "offset": 16})
        self.assertEqual(results[0]["form"], "ἔπεμπον")

    def test_persists_provider_forms_and_intersects_dialogue_tokens(self):
        records = [{
            "provider": "fixture",
            "provider_version": "1",
            "form": "κατέβην",
            "lemma": "καταβαίνω",
            "classification": "direct_lookup",
            "source": {"revision": "fixture"},
            "license": {"status": "test"},
        }, {
            "provider": "fixture",
            "provider_version": "1",
            "form": "καταβαίνει",
            "lemma": "καταβαίνω",
            "classification": "direct_lookup",
            "source": {"revision": "fixture"},
            "license": {"status": "test"},
        }]
        stored = self.index.store_lemma_forms(
            self.dialogue, self.version, "καταβαίνω", "fixture-fingerprint", records
        )
        cached = self.index.cached_lemma_forms(
            self.dialogue, self.version, "καταβαίνω", "fixture-fingerprint"
        )
        self.assertEqual(stored, cached)
        forms = self.index.observed_lemma_forms(
            self.dialogue, self.version, "καταβαίνω", "fixture-fingerprint"
        )
        self.assertEqual([item["form"] for item in forms], ["κατέβην"])
        self.assertEqual(forms[0]["count"], 1)
        self.assertEqual(forms[0]["occurrences"][0]["location"]["start"],
                         {"stephanus": "327a", "offset": 0})
        self.assertEqual(forms[0]["occurrences"][0]["division"],
                         {"type": "book", "label": "1"})

    def test_persists_typed_relations_separately_from_forms(self):
        records = [{
            "provider": "fixture-dictionary",
            "provider_version": "1",
            "source_lemma": "καταβαίνω",
            "target_lemma": "βαίνω",
            "relation_type": "etymological_relation",
            "direction": "directed",
            "source_fragment": "<etym lang=\"grc\">βαίνω</etym>",
            "source": {"revision": "fixture"},
            "license": {"status": "test"},
        }]
        stored = self.index.store_lemma_relations(
            self.dialogue, self.version, "καταβαίνω", "relation-fingerprint", records
        )
        cached = self.index.cached_lemma_relations(
            self.dialogue, self.version, "καταβαίνω", "relation-fingerprint"
        )
        self.assertEqual(stored, cached)
        self.assertEqual(cached[0]["target_lemma"], "βαίνω")
        self.assertIsNone(self.index.cached_lemma_relations(
            self.dialogue, self.version, "καταβαίνω", "different-fingerprint"
        ))
