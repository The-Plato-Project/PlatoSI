import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.cli import main
from platosi.profiles import Profiles
from platosi.registry import Registry


PROVIDER = """
class TestProvider:
    def __init__(self, manifest):
        self.manifest = manifest
    def available(self):
        return self.manifest['config'].get('available', True)
    def search(self, query, mode, limit):
        return [self.record(query)]
    def passage(self, edition, citation):
        return [self.record(citation)]
    def lookup(self, query, mode, limit):
        return [self.record(query)]
    def analyze(self, query, mode, limit):
        return [self.record(query)]
    def retrieve(self, query):
        return [self.record(query)]
    def record(self, query):
        return {'provider': self.manifest['id'], 'source': self.manifest['source'],
                'assertion': self.manifest['config']['assertion'], 'query': query}
def create_provider(manifest, root):
    return TestProvider(manifest)
"""


class ReaderProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.add_provider("corpus-a", "corpus", ["search", "passage"], "text A")
        self.add_provider("corpus-b", "corpus", ["search", "passage"], "text B")
        self.add_provider("dict-a", "dictionary", ["lookup"], "first interpretation")
        self.add_provider("dict-b", "dictionary", ["lookup"], "conflicting interpretation")
        self.add_provider("morph-a", "morphology", ["analyze"], "candidate A")
        self.add_provider("morph-b", "morphology", ["analyze"], "candidate B")
        self.add_provider("commentary", "scholarly", ["retrieve"], "commentary")
        self.add_provider("offline", "dictionary", ["lookup"], "not available", available=False)

    def tearDown(self):
        self.temp.cleanup()

    def add_provider(self, name, kind, capabilities, assertion, available=True):
        folder = self.root / "plugins" / name
        folder.mkdir(parents=True)
        manifest = {"id": name, "type": kind, "version": "1", "module": "provider.py",
                    "capabilities": capabilities, "source": {"revision": name},
                    "license": {"status": "test fixture"},
                    "config": {"assertion": assertion, "available": available}}
        (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "provider.py").write_text(PROVIDER, encoding="utf-8")

    def cli(self, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", ["platosi", "--root", str(self.root), *args]):
            with contextlib.redirect_stdout(output):
                main()
        return json.loads(output.getvalue())

    def test_profile_roundtrip_and_priority_across_resource_types(self):
        self.cli("profile", "save", "reader", "--resource", "dict-b", "--resource", "corpus-b",
                 "--resource", "dict-a", "--resource", "corpus-a",
                 "--resource", "morph-b", "--resource", "morph-a",
                 "--resource", "commentary")
        saved = self.cli("profile", "show", "reader")
        self.assertEqual(saved["resources"][:3], ["dict-b", "corpus-b", "dict-a"])
        self.assertFalse(saved["text_first"])
        self.assertEqual(self.cli("profile", "list")["reader"], Profiles(self.root).get("reader"))
        texts = self.cli("search", "x", "--profile", "reader")
        self.assertEqual(texts["available_providers"], ["corpus-b", "corpus-a"])
        dictionaries = self.cli("lookup", "x", "--profile", "reader")
        self.assertEqual(dictionaries["available_providers"], ["dict-b", "dict-a"])
        self.assertEqual([r["assertion"] for r in dictionaries["results"]],
                         ["conflicting interpretation", "first interpretation"])
        self.assertEqual([r["source"]["revision"] for r in dictionaries["results"]], ["dict-b", "dict-a"])
        analyses = self.cli("analyze", "x", "--profile", "reader")
        self.assertEqual([r["assertion"] for r in analyses["results"]], ["candidate B", "candidate A"])
        commentary = self.cli("retrieve", '{"passage":"327a"}', "--profile", "reader")
        self.assertEqual(commentary["results"][0]["query"], {"passage": "327a"})

    def test_inquiry_overrides_do_not_change_profile(self):
        self.cli("profile", "save", "reader", "--resource", "dict-a", "--resource", "dict-b")
        included = self.cli("lookup", "x", "--profile", "reader", "--include", "dict-b",
                            "--include", "dict-a")
        self.assertEqual(included["available_providers"], ["dict-b", "dict-a"])
        excluded = self.cli("lookup", "x", "--profile", "reader", "--exclude", "dict-a")
        self.assertEqual(excluded["available_providers"], ["dict-b"])
        self.assertEqual(excluded["inquiry_exclude"], ["dict-a"])
        self.assertFalse(next(p for p in excluded["providers"] if p["id"] == "dict-a")["selected"])
        self.assertEqual(self.cli("profile", "show", "reader")["resources"], ["dict-a", "dict-b"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("lookup", "x", "--include", "dict-a", "--exclude", "dict-a")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("lookup", "x", "--include", "dict-a", "--include", "dict-a")

    def test_text_first_requires_explicit_noncorpus_inclusion(self):
        self.add_provider("dict-danger", "dictionary", ["lookup"], "must not be loaded")
        (self.root / "plugins" / "dict-danger" / "provider.py").write_text(
            "raise RuntimeError('text-first loaded a dictionary')\n", encoding="utf-8")
        self.cli("profile", "save", "text", "--text-first", "--resource", "dict-a",
                 "--resource", "morph-a", "--resource", "corpus-a", "--resource", "commentary",
                 "--resource", "dict-danger")
        self.assertEqual(self.cli("search", "x", "--profile", "text")["available_providers"], ["corpus-a"])
        for operation, query in (("lookup", "x"), ("analyze", "x"), ("retrieve", "{}")):
            response = self.cli(operation, query, "--profile", "text")
            self.assertEqual(response["results"], [])
            self.assertIn("text-first mode", [s["reason"] for s in response["selected_resources"]])
        self.assertEqual(self.cli("lookup", "x", "--profile", "text", "--include", "dict-a")
                         ["available_providers"], ["dict-a"])
        self.assertEqual(self.cli("analyze", "x", "--profile", "text", "--include", "morph-a")
                         ["available_providers"], ["morph-a"])
        self.assertEqual(self.cli("retrieve", "{}", "--profile", "text", "--include", "commentary")
                         ["available_providers"], ["commentary"])

    def test_missing_disabled_and_unavailable_preferences_survive(self):
        resources = ["dict-a", "dict-b", "missing", "offline"]
        self.cli("profile", "save", "reader", *sum((["--resource", r] for r in resources), []))
        Registry(self.root).set_enabled("dict-b", False)
        shutil.rmtree(self.root / "plugins" / "dict-a")
        result = self.cli("lookup", "x", "--profile", "reader")
        self.assertEqual(result["available_providers"], [])
        self.assertEqual([s["reason"] for s in result["selected_resources"]],
                         ["not installed", "disabled", "not installed", "source or current index unavailable"])
        self.assertEqual(self.cli("profile", "show", "reader")["resources"], resources)
        override = self.cli("lookup", "x", "--profile", "reader", "--include", "dict-b",
                            "--include", "missing")
        self.assertEqual([s["reason"] for s in override["selected_resources"]],
                         ["disabled", "not installed"])
        self.add_provider("dict-a", "dictionary", ["lookup"], "restored")
        Registry(self.root).set_enabled("dict-b", True)
        result = self.cli("lookup", "x", "--profile", "reader")
        self.assertEqual(result["available_providers"], ["dict-a", "dict-b"])
        self.assertEqual(self.cli("profile", "show", "reader")["resources"], resources)

    def test_unselected_provider_is_not_loaded(self):
        self.add_provider("untrusted", "dictionary", ["lookup"], "irrelevant")
        (self.root / "plugins" / "untrusted" / "provider.py").write_text(
            "raise RuntimeError('unselected provider was loaded')\n", encoding="utf-8")
        self.cli("profile", "save", "reader", "--resource", "dict-a")
        result = self.cli("lookup", "x", "--profile", "reader")
        self.assertEqual(result["available_providers"], ["dict-a"])
        state = next(p for p in result["providers"] if p["id"] == "untrusted")
        self.assertFalse(state["selected"])
        self.assertIsNone(state["available"])

    def test_validation_and_empty_profile(self):
        self.cli("profile", "save", "empty")
        self.assertEqual(self.cli("lookup", "x", "--profile", "empty")["results"], [])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("profile", "save", "bad", "--resource", "dict-a", "--resource", "dict-a")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("search", "x", "--profile", "unknown")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("retrieve", "[]")
        self.assertEqual(list(self.cli("profile", "list")), ["empty"])


if __name__ == "__main__":
    unittest.main()
