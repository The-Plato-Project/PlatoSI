import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.person_research import PersonResearch


class PersonResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        if "wikidata.org" in url:
            return {"search": [{"id": "Q1", "label": "Glaucon",
                                "description": "older brother of Plato"}]}
        if "wikipedia.org" in url:
            return {"query": {"pages": [{"index": 1, "title": "Glaucon",
                                         "fullurl": "https://en.wikipedia.org/wiki/Glaucon",
                                         "extract": "Glaucon was Plato's brother."}]}}
        return {"query": {"pages": [{"title": "Γλαύκων",
                                     "fullurl": "https://en.wiktionary.org/wiki/Γλαύκων",
                                     "extract": "From γλαυκός, gleaming."}]}}

    @staticmethod
    def model(prompt, schema):
        if "search candidates" in prompt:
            value = {"roots": ["τις"]}
        else:
            value = {
                "person": "Glaucon is identified as Plato's brother. [S1]",
                "name_meaning": "The name is derived from γλαυκός. [S3]",
                "relationships": ["Brother of Plato. [S1]"],
            }
        return {"text": json.dumps(value, ensure_ascii=False), "model": "fixture"}

    @staticmethod
    def dictionary(term):
        if term != "γλαυκος":
            return []
        return [{
            "headword": "γλαυκός",
            "entry_xml": "<div2><head>γλαυκός</head>gleaming</div2>",
            "source": {"repository": "https://example.test/lsj", "revision": "abc"},
        }]

    def test_research_is_grounded_and_cached(self):
        service = PersonResearch(self.root, self.fetch)
        first = service.research(
            "Γλαύκων", "Republic 327a", self.model,
            {"provider": "ollama", "model": "fixture"}, self.dictionary
        )
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["roots"], ["γλαυκός"])
        self.assertEqual(len(first["sources"]), 4)
        self.assertIn("[S1]", first["summary"]["person"])
        call_count = len(self.calls)
        second = service.research(
            "Γλαύκων", "Republic 327a", self.model,
            {"provider": "ollama", "model": "fixture"}, self.dictionary
        )
        self.assertEqual(len(self.calls), call_count)
        self.assertTrue(second["cache"]["summary_model_hit"])


if __name__ == "__main__":
    unittest.main()
