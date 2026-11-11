"""Checks for the in-process ikelos/Morpheus provider."""

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platosi.profiles import select
from platosi.reader_api import ReaderApi
from platosi.registry import Registry


class MorpheusFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(
            ROOT / "plugins" / "morpheus",
            self.root / "plugins" / "morpheus",
        )
        self.registry = Registry(self.root)
        self.addCleanup(self.registry.close)
        self.provider = self.registry.providers["morpheus"].load()

    def configured(self, **overrides):
        manifest = copy.deepcopy(self.provider.manifest)
        manifest["config"].update(overrides)
        return type(self.provider)(manifest, self.root)


class MorpheusAnalysisTests(MorpheusFixture):
    def test_imperfect_retains_lemma_homograph_and_grammar(self):
        records = self.provider.analyze("ἀπῇμεν", "exact", 20)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["lemma"], "ἄπειμι")
        self.assertEqual(record["analysis"]["headword"], "ἄπειμι2")
        self.assertEqual(record["analysis"]["homograph"], "2")
        self.assertEqual(record["analysis"]["features"], {
            "part_of_speech": "verb",
            "tense": "imperfect",
            "mood": "indicative",
            "voice": "active",
            "person": "1st",
            "number": "plural",
            "stem_type": "irreg_mi",
        })
        self.assertEqual(record["analysis"]["engine"], {
            "name": "ikelos",
            "version": "0.1.0.dev1",
        })

    def test_republic_forms_and_ambiguity_survive(self):
        forms = (
            "κατέβην",
            "καταβαίνων",
            "καταβῆναι",
            "καταβαίνῃ",
            "καταβὰς",
            "καταβαίνειν",
        )
        for form in forms:
            with self.subTest(form=form):
                lemmas = {
                    record["lemma"]
                    for record in self.provider.analyze_complete(form)
                }
                self.assertIn("καταβαίνω", lemmas)
        self.assertIn(
            "καθάπτω",
            {
                record["lemma"]
                for record in self.provider.analyze_complete("καταβῆναι")
            },
        )

    def test_capitalized_name_keeps_all_candidate_readings(self):
        records = self.provider.analyze_complete("Πολεμάρχου")
        self.assertGreaterEqual(len(records), 2)
        self.assertIn(True, {record["analysis"]["proper"] for record in records})
        self.assertIn(False, {record["analysis"]["proper"] for record in records})

    def test_dependency_identity_and_failures_are_explicit(self):
        identity = self.provider.index_identity()
        self.assertEqual(identity["ikelos_version"], "0.1.0.dev1")
        self.assertEqual(
            identity["source"]["wheel_sha256"],
            "908f58a9136538f9f65a13fdb858d8f86e9e542914195493d09cade60df31ae9",
        )
        wrong = self.configured(ikelos_version="9.9.9")
        self.assertFalse(wrong.available())
        with self.assertRaisesRegex(RuntimeError, "9.9.9 is required"):
            wrong.analyze_complete("λόγος")
        with self.assertRaises(ValueError):
            self.configured(strict_case="yes")
        for form, mode, limit in (
            ("", "exact", 1),
            ("word", "exact", 1),
            ("δύο λέξεις", "exact", 1),
            ("λόγος", "accent-insensitive", 1),
            ("λόγος", "exact", 0),
        ):
            with self.subTest(form=form, mode=mode, limit=limit):
                with self.assertRaises(ValueError):
                    self.provider.analyze(form, mode, limit)


class MorpheusPluginTests(MorpheusFixture):
    def test_discovery_activation_profiles_and_removal_need_no_registry_changes(self):
        registration = self.registry.providers["morpheus"]
        self.assertEqual(registration.manifest["capabilities"], ["analyze"])
        self.assertFalse(registration.enabled)
        self.assertEqual(list(self.registry.active("analyze")), [])
        self.registry.set_enabled("morpheus", True)
        self.assertEqual(
            [item.manifest["id"] for item, _ in self.registry.active("analyze")],
            ["morpheus"],
        )
        self.assertEqual(
            select(self.registry, "analyze", include=["morpheus"])[1][0][0]
            .manifest["id"],
            "morpheus",
        )
        self.assertEqual(
            select(self.registry, "analyze", exclude=["morpheus"])[1],
            [],
        )
        self.assertEqual(list(self.registry.active("lemma_forms")), [])
        self.registry.set_enabled("morpheus", False)
        (self.root / "plugins" / "morpheus" / "plugin.json").unlink()
        self.assertEqual(Registry(self.root).providers, {})

    def test_reader_api_keeps_provider_answers_and_isolates_failure(self):
        folder = self.root / "plugins" / "alternate"
        folder.mkdir()
        (folder / "plugin.json").write_text(json.dumps({
            "id": "alternate",
            "type": "morphology",
            "version": "test",
            "module": "provider.py",
            "capabilities": ["analyze"],
            "source": {"revision": "fixture"},
            "license": {"status": "fixture"},
        }), encoding="utf-8")
        (folder / "provider.py").write_text(
            "class Provider:\n"
            "    def available(self): return True\n"
            "    def analyze(self, form, mode, limit):\n"
            "        return [{'provider': 'alternate', 'lemma': 'ἀπέρχομαι', "
            "'form': form}]\n"
            "def create_provider(manifest, root): return Provider()\n",
            encoding="utf-8",
        )
        self.registry.set_enabled("morpheus", True)
        api = ReaderApi(self.root)
        self.addCleanup(api.close)
        result = api.execute("word.analyze", {"form": "ἀπῇμεν"})
        self.assertEqual(
            {(record["provider"], record["lemma"])
             for record in result["analyses"]["records"]},
            {("morpheus", "ἄπειμι"), ("alternate", "ἀπέρχομαι")},
        )
        candidates = ReaderApi.organize_possibilities(
            result["analyses"]["records"]
        )
        morpheus = next(
            candidate
            for candidate in candidates
            if candidate["lemma"] == "ἄπειμι"
        )["candidates"][0]
        self.assertEqual(morpheus["headword"], "ἄπειμι2")
        self.assertEqual(morpheus["features"]["tense"], "imperfect")

        with api._registry_lease() as registry:
            active = registry.providers["morpheus"].load()
        with patch.object(active, "_library", side_effect=OSError("analyzer failed")):
            partial = api.execute("word.analyze", {"form": "Πολεμάρχου"})
        self.assertEqual(partial["analyses"]["status"], "partial")
        self.assertEqual(
            [record["provider"] for record in partial["analyses"]["records"]],
            ["alternate"],
        )
        self.assertTrue(
            any(
                "morpheus" in warning and "analyzer failed" in warning
                for warning in partial["analyses"]["warnings"]
            )
        )


if __name__ == "__main__":
    unittest.main()
