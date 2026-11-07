import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.person_research import PersonResearch
from platosi.research_sources import ResearchSources


HUMANISTICA_EXCERPT = (
    "Polemarchus Πολέμαρχος Life ? – 404 BCE Father Cephalus Category metic. "
    "Eldest son of Cephalus and brother of Lysias. He inherits the conversation "
    "from his father in Republic I. He was put to death by the Thirty in 404 and "
    "his property confiscated, an event narrated by his brother Lysias. Sources "
    "Plato, Republic I.331d–336a; Lysias, Against Eratosthenes 4 ff."
)
ATHENIAN_EXCERPT = (
    "Πολέμαρχος of Sicily, Syracuse, c. 455-403 BC: RE (1); cf. APF pp. 587-90 "
    "C 9 (LGPN III.A (43)) (s. Κέφαλος) [ID: 69789] [Foreign resident]"
)
LYSIAS_EXCERPT = (
    "[12.6] Theognis and Peison stated before the Thirty that they had an excellent "
    "pretext for appearing to punish while in reality making money. "
    "[12.7] They resolved to seize ten resident aliens. "
    "[12.16] Eratosthenes had arrested him in the street and taken him off to prison. "
    "[12.17] Polemarchus received from the Thirty their accustomed order to drink hemlock, "
    "with no statement made as to the reason for his execution: still less was he allowed "
    "to be tried and defend himself. "
    "[12.18] They did not permit his funeral to be conducted from any of their houses. "
    "[12.19] They had seven hundred shields of ours, all that silver and gold, copper, "
    "jewellery, furniture, women's apparel, and a hundred and twenty slaves."
)


class PersonResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        self.config = self.root / "config" / "name-research-sources.json"
        shutil.copyfile(ROOT / "config" / self.config.name, self.config)
        self.calls = []
        self.citation_calls = []

    def tearDown(self):
        self.temp.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        adapter = parse_qs(urlsplit(url).fragment).get("adapter", [""])[0]
        if adapter == "humanistica-plato":
            return {"people": [{
                "slug": "p-polemarchus",
                "title": "Polemarchus",
                "greek": "Πολέμαρχος",
                "url": "https://humanisticadigitalia.eu/GreekTexts/Plato/#p-polemarchus",
                "excerpt": HUMANISTICA_EXCERPT,
                "citations": [{
                    "title": "Lysias, Against Eratosthenes 4 ff.",
                    "url": (
                        "https://www.perseus.tufts.edu/hopper/text?"
                        "doc=Perseus:text:1999.01.0153:speech=12"
                    ),
                }],
            }]}
        if adapter == "athenian-onomasticon":
            return {"entries": [{
                "id": "69789",
                "title": "Πολέμαρχος — Onomasticon ID 69789",
                "url": "https://athnames.org/r4.php?id=69789",
                "excerpt": ATHENIAN_EXCERPT,
            }]}
        raise AssertionError(f"Unexpected source URL: {url}")

    def citation_fetch(self, citation, names):
        self.citation_calls.append((citation, names))
        return {
            "title": citation["title"],
            "url": citation["url"],
            "excerpt": LYSIAS_EXCERPT,
            "edition": "tlg0540.tlg012.perseus-eng2.xml",
        }

    def service(self):
        return PersonResearch(
            self.root,
            self.fetch,
            citation_fetch=self.citation_fetch,
        )

    @staticmethod
    def model(prompt, schema):
        if "source_ids" in schema["properties"]:
            return {"text": json.dumps({"source_ids": ["S1", "S2", "S3"]}), "model": "fixture"}
        if "accepted_indices" in schema["properties"]:
            statements = json.loads(prompt.split("STATEMENTS: ", 1)[1])
            return {
                "text": json.dumps({"accepted_indices": list(range(len(statements)))}),
                "model": "fixture",
            }
        return {
            "text": json.dumps({"statements": [{
                "text": "Polemarchus was a metic, the son of Cephalus and brother of Lysias.",
                "quotes": [{
                    "id": "S1",
                    "quote": "Father Cephalus Category metic. Eldest son of Cephalus and brother of Lysias.",
                }],
            }, {
                "text": "He was put to death by the Thirty in 404 BCE and his property was confiscated.",
                "quotes": [{
                    "id": "S1",
                    "quote": "He was put to death by the Thirty in 404 and his property confiscated",
                }],
            }, {
                "text": "Lysias alleged that members of the Thirty used punishment as a pretext for making money.",
                "quotes": [{
                    "id": "S2",
                    "quote": "they had an excellent pretext for appearing to punish while in reality making money",
                }],
            }, {
                "text": "Eratosthenes arrested Polemarchus in the street and took him to prison.",
                "quotes": [{
                    "id": "S2",
                    "quote": "Eratosthenes had arrested him in the street and taken him off to prison.",
                }],
            }, {
                "text": "The Thirty ordered him to drink hemlock without stating a reason or allowing a trial and defense.",
                "quotes": [{
                    "id": "S2",
                    "quote": (
                        "Polemarchus received from the Thirty their accustomed order to drink hemlock, "
                        "with no statement made as to the reason for his execution: still less was he "
                        "allowed to be tried and defend himself."
                    ),
                }],
            }, {
                "text": "His family was denied a funeral from their homes, and the regime seized extensive family property.",
                "quotes": [{
                    "id": "S2",
                    "quote": "They did not permit his funeral to be conducted from any of their houses.",
                }, {
                    "id": "S2",
                    "quote": (
                        "They had seven hundred shields of ours, all that silver and gold, copper, "
                        "jewellery, furniture, women's apparel, and a hundred and twenty slaves."
                    ),
                }],
            }, {
                "text": "The Athenian Onomasticon records him as a foreign resident from Syracuse.",
                "quotes": [{
                    "id": "S3",
                    "quote": "Πολέμαρχος of Sicily, Syracuse, c. 455-403 BC: RE (1); cf. APF pp. 587-90 C 9",
                }],
            }]}),
            "model": "fixture",
        }

    def test_scholarly_sources_produce_cited_overview_and_reuse_cache(self):
        service = self.service()
        prompts = []

        def model(prompt, schema):
            prompts.append(prompt)
            self.assertNotIn("Wikipedia", prompt)
            self.assertNotIn("Wikidata", prompt)
            return self.model(prompt, schema)

        first = service.research(
            "Πολέμαρχος", "[327b] Πολέμαρχος", model, {"model": "fixture"}, "republic"
        )
        second = service.research(
            "Πολέμαρχος", "[327b] Πολέμαρχος", model, {"model": "fixture"}, "republic"
        )
        self.assertEqual(first["contract"], "platosi.person-research.v3")
        self.assertEqual(first["status"], "ok")
        self.assertEqual(len(prompts), 3)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.citation_calls), 1)
        self.assertEqual(
            {source["provider"] for source in first["sources"]},
            {
                "Platonis Humanistica Digitalia",
                "Platonis Humanistica Digitalia citation",
                "Athenian Onomasticon",
            },
        )
        self.assertEqual(first["sources"][0]["relevance"], "plato_dialogue")
        self.assertIn("hemlock", first["overview"])
        self.assertIn("funeral", first["overview"])
        self.assertNotIn("philosopher", first["overview"].casefold())
        self.assertNotIn("office", first["overview"].casefold())
        self.assertTrue(second["cache"]["summary_model_hit"])

    def test_duplicate_urls_are_deduplicated_and_old_note_ids_survive(self):
        value = json.loads(self.config.read_text(encoding="utf-8"))
        value["sources"].append({
            **value["sources"][0],
            "id": "duplicate-humanistica",
            "priority": 11,
        })
        self.config.write_text(json.dumps(value), encoding="utf-8")
        service = self.service()
        old_url = (
            "https://www.wikidata.org/w/api.php?action=wbsearchentities"
            "&search=Πολέμαρχος&language=en&format=json"
        )
        service.cache.web(old_url, lambda _url: {"search": [
            {"id": "Q3371179", "label": "Polemarchus"},
        ]})

        result = service.research("Πολέμαρχος", "327b", self.model, {})

        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.citation_calls), 1)
        self.assertEqual(len(result["sources"]), 3)
        candidates = {candidate["id"]: candidate for candidate in result["candidates"]}
        self.assertIn("wikidata:Q3371179", candidates)
        self.assertEqual(candidates["wikidata:Q3371179"]["sources"], [])

    def test_invalid_model_output_retries_without_caching_success(self):
        service = self.service()
        writes = []

        def invalid_model(prompt, schema):
            if "source_ids" in schema["properties"]:
                return self.model(prompt, schema)
            writes.append(prompt)
            return {"text": json.dumps({"overview": "Unsupported claim. [S99]"})}

        result = service.research("Πολέμαρχος", "327b", invalid_model, {"model": "bad"})
        self.assertEqual(len(writes), 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["overview"], "")
        self.assertEqual(len(result["sources"]), 3)
        self.assertIn("No usable research synthesis", result["warnings"][0])

        recovered = service.research("Πολέμαρχος", "327b", self.model, {"model": "bad"})
        self.assertEqual(recovered["status"], "ok")
        self.assertFalse(recovered["cache"]["summary_model_hit"])

    def test_source_configuration_requests_and_html_parsers(self):
        self.assertEqual(
            PersonResearch._model_json('```json\n{"source_ids":["S1"]}\n```'),
            {"source_ids": ["S1"]},
        )
        value = json.loads(self.config.read_text(encoding="utf-8"))
        for source in value["sources"]:
            source["enabled"] = False
        self.config.write_text(json.dumps(value), encoding="utf-8")
        result = self.service().research(
            "Πολέμαρχος", "327b", self.model, {}
        )
        self.assertEqual(result["status"], "empty")
        self.assertEqual(self.calls, [])

        humanistica = {
            **value["sources"][0],
            "enabled": True,
        }
        humanistica_url = ResearchSources.request_url(humanistica, "Πολέμαρχος")
        self.assertEqual(
            parse_qs(urlsplit(humanistica_url).fragment)["adapter"],
            ["humanistica-plato"],
        )
        athenian = {
            **value["sources"][1],
            "enabled": True,
        }
        athenian_url = ResearchSources.request_url(athenian, "Πολέμαρχος")
        self.assertEqual(
            parse_qs(urlsplit(athenian_url).query)["name"],
            ["Πολεμαρχοσ^"],
        )

        humanistica_html = (
            '<section class="page" id="p-polemarchus">'
            '<div class="crumb">Persons · metic</div>'
            '<h2>Polemarchus <span class="greek">Πολέμαρχος</span></h2>'
            f"<p>{HUMANISTICA_EXCERPT}</p>"
            '<h3>Sources</h3><p><a href="#d-republic">Plato, Republic I</a>; '
            '<a href="https://www.perseus.tufts.edu/hopper/text?'
            'doc=Perseus:text:1999.01.0153:speech=12">'
            'Lysias, Against Eratosthenes</a> 4 ff.</p></section>'
        )
        dataset = ResearchSources.parse_humanistica(
            humanistica_html, "https://humanisticadigitalia.eu/GreekTexts/Plato/"
        )
        matches = ResearchSources.filter_humanistica(dataset, "Πολέμαρχος")
        self.assertEqual(matches["people"][0]["title"], "Polemarchus")
        self.assertEqual(
            matches["people"][0]["citations"][0]["title"],
            "Lysias, Against Eratosthenes 4 ff.",
        )

        athenian_html = (
            '<code id="cu-69789">https://athnames.org/r4.php?id=69789</code>'
            '<button>copy</button></div>17. '
            f"{ATHENIAN_EXCERPT}</p>"
        )
        entries = ResearchSources.parse_athenian_onomasticon(athenian_html)["entries"]
        self.assertEqual(entries[0]["id"], "69789")
        self.assertIn("Foreign resident", entries[0]["excerpt"])

        value["sources"][0]["adapter"] = "unsupported"
        self.config.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported research source adapter"):
            ResearchSources(self.config)

    def test_required_historical_sources_cannot_be_dropped(self):
        service = self.service()
        evidence = [
            {"id": "S1", "title": "Polemarchus", "kind": "plato_prosopography",
             "provider": "Humanistica", "text": HUMANISTICA_EXCERPT,
             "minimum_statements": 2},
            {"id": "S2", "title": "Lysias 12", "kind": "cited_primary_text",
             "provider": "Perseus", "text": LYSIAS_EXCERPT,
             "minimum_statements": 3},
            {"id": "S3", "title": "Other person", "kind": "scholarly_prosopography",
             "provider": "Onomasticon", "text": "Another same-name person.",
             "minimum_statements": 0},
        ]

        def selector(_prompt, _schema):
            return {"text": json.dumps({"source_ids": ["S3"]})}

        selected = service._select_sources(
            "Πολέμαρχος", "republic", "[327b] Πολέμαρχος", evidence, selector
        )
        self.assertEqual(selected, {"S1", "S2", "S3"})


if __name__ == "__main__":
    unittest.main()
