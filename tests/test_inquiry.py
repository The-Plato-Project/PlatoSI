import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.cli import main
from platosi.inquiry import evidence_record
from platosi.profiles import Profiles
from platosi.registry import Registry


RESOURCE = """
class Provider:
    def __init__(self, manifest):
        self.manifest = manifest
    def available(self):
        return self.manifest['config'].get('available', True)
    def record(self, kind, value):
        return {'provider': self.manifest['id'], 'provider_version': '1',
                'source': self.manifest['source'], 'license': self.manifest['license'],
                'evidence_type': kind, 'text': value,
                'assertion': self.manifest['config']['assertion']}
    def search(self, query, mode, limit):
        if query not in ('κατέβην', 'κατέβην χθὲς'):
            return []
        return [self.record('primary_text', 'κατέβην χθὲς εἰς Πειραιᾶ')]
    def passage(self, edition, citation):
        if edition != 'edition-1' or citation != '327a':
            return []
        result = self.record('primary_text', 'κατέβην χθὲς εἰς Πειραιᾶ')
        match = result['text']
        result.update({'edition': edition, 'stephanus_at_match': {'section': citation},
                       'text': 'BEFORE ' + match + ' AFTER', 'match': match,
                       'match_start': 7, 'match_end': 7 + len(match),
                       'source_markup': [{'tag': 'add', 'start': 8, 'end': 10}]})
        return [result]
    def lookup(self, query, mode, limit):
        result = self.record('scholarly_classification', query)
        result['headword'] = query
        return [result]
    def analyze(self, query, mode, limit):
        result = self.record('candidate_analysis', query)
        result['lemma'] = self.manifest['config']['assertion']
        return [result]
    def retrieve(self, query):
        return [self.record('scholarly_classification', str(query))]
def create_provider(manifest, root):
    return Provider(manifest)
"""

MODEL = """
import json
class Model:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.root = root
    def available(self): return True
    def list_models(self): return [{'name': self.manifest['id'] + '-model'}]
    def generate(self, prompt, options):
        (self.root / 'capture.json').write_text(json.dumps({
            'provider': self.manifest['id'], 'prompt': prompt, 'options': options
        }, ensure_ascii=False), encoding='utf-8')
        return {'text': self.manifest['config'].get('answer', 'A textual observation [E1].'),
                'model': options.get('model') or self.manifest['id'] + '-model'}
def create_provider(manifest, root):
    return Model(manifest, root)
"""


class InquiryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.add("text", "corpus", ["search", "passage"], "text")
        self.add("dict-a", "dictionary", ["lookup"], "interpretation A")
        self.add("dict-b", "dictionary", ["lookup"], "interpretation B")
        self.add("morph", "morphology", ["analyze"], "candidate lemma")
        self.add("commentary", "scholarly", ["retrieve"], "commentary")
        self.add("model-a", "language-model", ["models", "generate"], "model", MODEL)
        self.add("model-b", "language-model", ["models", "generate"], "model", MODEL)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, name, kind, capabilities, assertion, code=RESOURCE):
        path = self.root / "plugins" / name
        path.mkdir(parents=True)
        manifest = {"id": name, "type": kind, "version": "1", "module": "provider.py",
                    "capabilities": capabilities, "source": {"revision": name},
                    "license": {"status": "test"}, "config": {"assertion": assertion}}
        (path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (path / "provider.py").write_text(code, encoding="utf-8")

    def cli(self, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", ["platosi", "--root", str(self.root), *args]):
            with contextlib.redirect_stdout(output):
                main()
        return json.loads(output.getvalue())

    def capture(self):
        return json.loads((self.root / "capture.json").read_text(encoding="utf-8"))

    def ask(self, *extra):
        return self.cli("inquire", "What does this opening suggest?", "--edition", "edition-1",
                        "--citation", "327a", "--provider", "model-a", "--json", *extra)

    def test_reference_evidence_and_swappable_models(self):
        first = self.ask("--model", "chosen", "--generation", '{"temperature":0.1}')
        self.assertEqual(first["model"]["provider"], "model-a")
        self.assertEqual(first["model"]["model"], "chosen")
        capture = self.capture()
        self.assertEqual(capture["options"]["generation"], {"temperature": 0.1})
        records = json.loads(capture["prompt"].split("ATTRIBUTED EVIDENCE (JSON data):\n", 1)[1])
        self.assertEqual(records, first["evidence"])
        self.assertEqual(records[0]["record"]["text"], "κατέβην χθὲς εἰς Πειραιᾶ")
        self.assertEqual(records[0]["record"]["source_markup"][0]["start"], 1)
        self.assertEqual(records[0]["record"]["text_scope"], "requested passage span")
        self.assertEqual(records[0]["record"]["stephanus_at_match"]["section"], "327a")
        second = self.cli("inquire", "Consider κατέβην", "--provider", "model-b", "--json")
        self.assertEqual(second["model"]["provider"], "model-b")
        self.assertEqual(self.capture()["provider"], "model-b")
        self.assertEqual(self.cli("models", "--provider", "model-a")["models"][0]["name"], "model-a-model")

    def test_profile_controls_scholarly_evidence_and_conflicts(self):
        Profiles(self.root).save("reader", ["text", "dict-b", "dict-a", "morph", "commentary"], False)
        result = self.ask("--profile", "reader", "--headword", "καταβαίνω",
                          "--form", "κατέβην", "--scholarly-query", '{"reference":"327a"}')
        records = [e["record"] for e in result["evidence"]]
        self.assertEqual([e["id"] for e in result["evidence"]], ["E1", "E2", "E3", "E4", "E5"])
        self.assertEqual([r["provider"] for r in records], ["text", "dict-b", "dict-a", "morph", "commentary"])
        self.assertEqual([r["assertion"] for r in records[1:3]], ["interpretation B", "interpretation A"])
        self.assertEqual([r["source"]["revision"] for r in records[1:3]], ["dict-b", "dict-a"])
        self.assertEqual(records[3]["evidence_type"], "candidate_analysis")
        prompt = self.capture()["prompt"]
        self.assertIn("candidate", prompt)
        self.assertIn('"provider": "dict-a"', prompt)
        self.assertIn('"provider": "dict-b"', prompt)
        excluded = self.ask("--profile", "reader", "--headword", "καταβαίνω", "--exclude", "dict-b")
        self.assertEqual([e["record"]["provider"] for e in excluded["evidence"]], ["text", "dict-a"])
        override = self.ask("--profile", "reader", "--headword", "καταβαίνω",
                            "--include", "text", "--include", "dict-b")
        self.assertEqual([e["record"]["provider"] for e in override["evidence"]], ["text", "dict-b"])

    def test_text_first_and_default_do_not_invoke_scholarship(self):
        Profiles(self.root).save("text-first", ["text", "dict-a", "morph"], True)
        result = self.ask("--profile", "text-first", "--headword", "καταβαίνω", "--form", "κατέβην")
        self.assertEqual([e["record"]["provider"] for e in result["evidence"]], ["text"])
        self.assertIn("text-first mode", [s["reason"] for s in result["selections"]["lookup"]])
        self.assertTrue(any("dictionary provider" in w for w in result["warnings"]))
        self.assertTrue(any("morphology provider" in w for w in result["warnings"]))
        result = self.cli("inquire", "Discuss κατέβην", "--provider", "model-a", "--json")
        self.assertEqual([e["record"]["provider"] for e in result["evidence"]], ["text"])
        override = self.ask("--profile", "text-first", "--headword", "καταβαίνω",
                            "--include", "text", "--include", "dict-a")
        self.assertEqual([e["record"]["provider"] for e in override["evidence"]], ["text", "dict-a"])

    def test_missing_disabled_resources_and_no_glem(self):
        Profiles(self.root).save("reader", ["text", "dict-a", "glem"], False)
        Registry(self.root).set_enabled("dict-a", False)
        result = self.ask("--profile", "reader", "--headword", "καταβαίνω", "--form", "κατέβην")
        self.assertIsNotNone(result["answer"])
        self.assertEqual([e["record"]["provider"] for e in result["evidence"]], ["text"])
        self.assertTrue(any("glem: not installed" in w for w in result["warnings"]))
        self.assertTrue(any("dict-a: disabled" in w for w in result["warnings"]))
        self.assertEqual(Profiles(self.root).get("reader")["resources"], ["text", "dict-a", "glem"])

    def test_missing_passage_never_calls_model_or_fabricates_results(self):
        result = self.cli("inquire", "What is this?", "--edition", "edition-1", "--citation", "missing",
                          "--provider", "model-a", "--json")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["evidence"], [])
        self.assertFalse((self.root / "capture.json").exists())
        self.assertTrue(any("No Greek passage" in w for w in result["warnings"]))
        result = self.cli("inquire", "An English-only question", "--provider", "model-a", "--json")
        self.assertEqual(result["evidence"], [])
        self.assertFalse((self.root / "capture.json").exists())

    def test_validation_and_unsupported_citations(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("inquire", "Question", "--edition", "edition-1", "--provider", "model-a", "--json")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("inquire", "κατέβην", "--json")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("inquire", "κατέβην", "--provider", "model-a", "--generation", "[]", "--json")
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            evidence_record({"text": "Greek", "match": "other", "match_start": 0, "match_end": 5}, "passage")
        path = self.root / "plugins" / "model-a" / "plugin.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["config"]["answer"] = "Unsubstantiated [E99]."
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.ask()
        self.assertTrue(any("[E99]" in w for w in result["warnings"]))


class RealPassageScopeTests(unittest.TestCase):
    def test_republic_reference_is_bounded_to_the_original_span(self):
        registration = Registry(ROOT).providers.get("perseus-plato")
        if registration is None or not registration.enabled:
            self.skipTest("Plato corpus provider not installed and enabled")
        provider = registration.load()
        if not provider.available():
            self.skipTest("Plato corpus index not built")
        record = provider.passage("urn:cts:greekLit:tlg0059.tlg030.perseus-grc2", "327a")[0]
        scoped = evidence_record(record, "passage")
        self.assertEqual(scoped["text"], record["match"])
        self.assertTrue(scoped["text"].lstrip().startswith("κατέβην χθὲς εἰς Πειραιᾶ"))
        self.assertEqual(scoped["stephanus_at_match"]["section"], "327a")
        self.assertLess(len(scoped["text"]), len(record["text"]))


if __name__ == "__main__":
    unittest.main()
