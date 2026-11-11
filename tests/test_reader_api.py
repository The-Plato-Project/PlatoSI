import json
import queue
import subprocess
import sys
import threading
import unicodedata
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.cancellation import Cancelled
from platosi.reader_api import ReaderApi
from platosi.reader_protocol import serve
from platosi.registry import Registry
import test_retrieval


class ReaderApiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_retrieval.PluginFixtureTests("test_duplicate_ids_and_ambiguity")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.api = ReaderApi(self.fixture.root)
        self.addCleanup(self.api.close)
        self.edition = "urn:cts:greekLit:tlg0059.tlg030.perseus-grc2"

    def test_sequential_requests_reuse_registry_until_configuration_changes(self):
        with patch("platosi.reader_api.Registry", wraps=Registry) as registry:
            self.api.execute("capabilities", {})
            self.api.execute("word.analyze", {"form": "κατέβην"})
            self.assertEqual(registry.call_count, 1)
            self.fixture.registry.set_enabled("fixture-morphology", True)
            self.api.execute("word.analyze", {"form": "κατέβην"})
            self.assertEqual(registry.call_count, 2)

    def test_concurrent_requests_share_one_registry(self):
        barrier = threading.Barrier(4)

        def discover():
            barrier.wait(timeout=5)
            return self.api.execute("capabilities", {})

        with patch("platosi.reader_api.Registry", wraps=Registry) as registry:
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(lambda _: discover(), range(4)))
            self.assertTrue(all(result["capabilities"] for result in results))
            self.assertEqual(registry.call_count, 1)

    def test_discovery_and_unavailable_morphology_are_explicit(self):
        result = self.api.execute("capabilities", {})
        operations = {item["operation"]: item for item in result["capabilities"]}
        self.assertTrue(operations["word.analyze"]["available"])
        self.assertFalse(operations["lemma.matchForms"]["available"])
        self.assertTrue(operations["text.search"]["available"])
        word = self.api.execute("word.analyze", {"form": "κατέβην"})
        self.assertEqual(word["analyses"]["status"], "unavailable")
        self.assertEqual(word["entries"]["status"], "ok")
        self.assertFalse(any("disabled" in warning for warning in word["analyses"]["warnings"]))


    def test_word_candidates_dictionary_and_exact_input_form_mappings(self):
        self.fixture.registry.set_enabled("fixture-morphology", True)
        word = self.api.execute("word.analyze", {"form": "κατέβην"})
        self.assertEqual({record["lemma"] for record in word["analyses"]["records"]}, {"καταβαίνω"})
        self.assertEqual(len(word["entries"]["records"]), 2)
        self.assertTrue(all(record["source"] and record["license"] for record in word["entries"]["records"]))
        search = self.api.execute("word.search", {"query": "κατέβην"})
        self.assertIn("καταβαίνω", {item["lemma"] for item in search["items"]})
        lexical = self.api.execute("word.lookup", {"lemma": "καταβαίνω", "scope": None})
        self.assertEqual(lexical["contract"], "platosi.lexical-evidence.v1")
        self.assertIsNone(lexical["target"]["location"])
        self.assertEqual(lexical["lemmas"][0]["lemma"], "καταβαίνω")
        self.assertEqual(lexical["lemmas"][0]["forms"], [])
        self.assertEqual(lexical["occurrences_status"], "unavailable")
        decomposed = unicodedata.normalize("NFD", "κατέβην")
        matches = self.api.execute("lemma.matchForms", {"lemma": "καταβαίνω",
                                                        "forms": ["κατέβην", decomposed, "χθὲς"]})
        self.assertEqual({record["input_form"] for record in matches["records"]}, {"κατέβην", decomposed})
        self.assertTrue(all(record["evidence"]["lemma"] == "καταβαίνω" for record in matches["records"]))
        with self.assertRaises(ValueError):
            self.api.execute("lemma.matchForms", {"lemma": "καταβαίνω", "forms": ["κατέβην", "κατέβην"]})

    def test_text_search_passage_and_invalid_requests(self):
        found = self.api.execute("text.search", {"text": "κατέβην"})
        self.assertEqual(found["status"], "ok")
        self.assertEqual(found["records"][0]["stephanus_at_match"]["section"], "327a")
        passage = self.api.execute("text.passage", {"edition": self.edition, "citation": "327a"})
        record = passage["records"][0]
        self.assertIn("κατέβην", record["match"])
        self.assertEqual(record["text"][record["match_start"]:record["match_end"]], record["match"])
        with self.assertRaises(ValueError):
            self.api.execute("text.search", {"text": " "})
        with self.assertRaises(ValueError):
            self.api.execute("not.an.operation", {})

    def test_stdio_protocol_uses_versioned_json_and_reports_invalid_messages(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from platosi.reader_protocol import serve; "
                "serve(sys.argv[2], sys.stdin.buffer, sys.stdout.buffer)")
        process = subprocess.Popen([sys.executable, "-u", "-c", code, str(ROOT / "src"), str(self.fixture.root)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.stdin.write(b"not-json\n")
            process.stdin.flush()
            invalid = json.loads(process.stdout.readline())
            self.assertEqual(invalid["status"], "invalid")
            request = {"version": 1, "id": "test", "operation": "text.search", "payload": {"text": "κατέβην"}}
            process.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertEqual(response["id"], "test")
            self.assertEqual(response["version"], 1)
            self.assertEqual(response["status"], "ok")
            self.assertEqual(response["result"]["records"][0]["match"], "κατέβην")
        finally:
            process.stdin.close()
            process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()


class ProtocolCancellationTests(unittest.TestCase):
    def test_cancel_acknowledgement_and_terminal_outcome(self):
        class Input:
            def __init__(self):
                self.lines = queue.Queue()

            def readline(self, limit):
                return self.lines.get(timeout=5)

            def put(self, value):
                self.lines.put((json.dumps(value) + "\n").encode())

        class Output:
            def __init__(self):
                self.lines = queue.Queue()

            def write(self, data):
                self.lines.put(json.loads(data))

            def flush(self):
                pass

        started = threading.Event()

        def execute(api, operation, payload, cancellation):
            started.set()
            while not cancellation.event.wait(0.01):
                pass
            raise Cancelled()

        source = Input()
        destination = Output()
        with patch.object(ReaderApi, "execute", execute):
            thread = threading.Thread(target=serve, args=(ROOT, source, destination))
            thread.start()
            source.put({"version": 1, "id": "first", "operation": "text.search", "payload": {}})
            self.assertTrue(started.wait(5))
            source.put({"version": 1, "id": "stop", "operation": "request.cancel", "payload": {"id": "first"}})
            messages = [destination.lines.get(timeout=5), destination.lines.get(timeout=5)]
            by_id = {message["id"]: message for message in messages}
            self.assertTrue(by_id["stop"]["result"]["requested"])
            self.assertEqual(by_id["first"]["status"], "cancelled")
            source.lines.put(b"")
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
