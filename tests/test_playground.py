import http.client
import json
import re
import sys
import tempfile
import threading
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.playground import Playground, Server, lan_addresses, private_ipv4, serve
from platosi.profiles import Profiles
from platosi.registry import Registry


MODEL = """
import json, time
class Model:
    def __init__(self, manifest, root):
        self.root = root
    def available(self): return True
    def list_models(self): return [{'name': 'mock-model'}]
    def chat(self, messages, options, cancellation):
        (self.root / 'capture.json').write_text(json.dumps({'messages': messages, 'options': options},
                                                          ensure_ascii=False), encoding='utf-8')
        while messages[-1]['content'] == 'WAIT':
            cancellation.check()
            time.sleep(0.01)
        return {'text': 'A response [E1]', 'model': options['model']}
    def generate(self, prompt, options):
        raise RuntimeError('grounded inquiry must use chat')
def create_provider(manifest, root): return Model(manifest, root)
"""

RESOURCE = """
class Provider:
    def __init__(self, manifest): self.manifest = manifest
    def available(self): return True
    def passage(self, edition, citation):
        if edition != 'edition' or citation != '327a': return []
        return [{'provider': self.manifest['id'], 'provider_version': '1',
                 'source': self.manifest['source'], 'license': self.manifest['license'],
                 'evidence_type': 'primary_text', 'text': 'κατέβην χθὲς',
                 'edition': edition, 'stephanus_at_match': {'section': citation}}]
    def lookup(self, query, mode, limit):
        return [{'provider': self.manifest['id'], 'provider_version': '1',
                 'source': self.manifest['source'], 'license': self.manifest['license'],
                 'evidence_type': 'scholarly_classification', 'headword': query}]
def create_provider(manifest, root): return Provider(manifest)
"""

class MarkupTests(unittest.TestCase):
    def test_javascript_element_ids_exist_and_are_unique(self):
        class IDs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = []

            def handle_starttag(self, tag, attrs):
                self.ids.extend(value for name, value in attrs if name == "id")

        parser = IDs()
        parser.feed((ROOT / "playground" / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        script = (ROOT / "playground" / "app.js").read_text(encoding="utf-8")
        for element_id in re.findall(r'\$\("([^"]+)"\)', script):
            self.assertIn(element_id, parser.ids)

    def test_lookup_element_ids_exist_and_are_unique(self):
        class IDs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = []

            def handle_starttag(self, tag, attrs):
                self.ids.extend(value for name, value in attrs if name == "id")

        parser = IDs()
        parser.feed((ROOT / "playground" / "lookup.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        script = (ROOT / "playground" / "lookup.js").read_text(encoding="utf-8")
        for element_id in re.findall(r'\$\("([^"]+)"\)', script):
            self.assertIn(element_id, parser.ids)

    def test_reader_element_ids_and_book_choices(self):
        class ReaderMarkup(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = []
                self.in_scope = False
                self.books = []

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if "id" in attributes:
                    self.ids.append(attributes["id"])
                if tag == "select" and attributes.get("id") == "scope":
                    self.in_scope = True
                if tag == "option" and self.in_scope:
                    self.books.append(attributes.get("value"))

            def handle_endtag(self, tag):
                if tag == "select":
                    self.in_scope = False

        parser = ReaderMarkup()
        parser.feed((ROOT / "playground" / "reader.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertEqual(parser.books, [str(book) for book in range(1, 11)])
        script = (ROOT / "playground" / "reader.js").read_text(encoding="utf-8")
        for element_id in re.findall(r'\$\("([^"]+)"\)', script):
            self.assertIn(element_id, parser.ids)



class PlaygroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.add("mock", "language-model", ["models", "generate", "chat"], MODEL)
        self.add("corpus", "corpus", ["passage"], RESOURCE)
        self.add("dict", "dictionary", ["lookup"], RESOURCE)
        self.app = Playground(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, name, kind, capabilities, code):
        folder = self.root / "plugins" / name
        folder.mkdir(parents=True)
        manifest = {"id": name, "type": kind, "version": "1", "module": "provider.py",
                    "capabilities": capabilities, "source": {"revision": name},
                    "license": {"status": "test"}, "config": {}}
        (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (folder / "provider.py").write_text(code, encoding="utf-8")

    def payload(self, message="A long dream", mode="free"):
        return {"provider": "mock", "model": "mock-model", "system_prompt": "My edited prompt",
                "mode": mode, "temperature": 0.8, "max_tokens": 1024,
                "messages": [{"role": "user", "content": message}]}

    def wait(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.app.get(job_id)
            if result["status"] != "running":
                return result
            time.sleep(0.01)
        self.fail("Generation did not complete")

    def capture(self):
        return json.loads((self.root / "capture.json").read_text(encoding="utf-8"))

    def test_free_conversation_prompt_history_and_no_retrieval(self):
        self.add("morph", "morphology", ["analyze"], RESOURCE)
        for resource in ("corpus", "dict", "morph"):
            (self.root / "plugins" / resource / "provider.py").write_text(
                "raise RuntimeError('free conversation loaded a resource')", encoding="utf-8")
        payload = self.payload("A dream " * 3000)
        result = self.wait(self.app.start(payload))
        self.assertEqual(result["status"], "complete")
        capture = self.capture()
        self.assertEqual(capture["messages"][0], {"role": "system", "content": "My edited prompt"})
        self.assertEqual(capture["messages"][1]["content"], payload["messages"][0]["content"])
        self.assertEqual(capture["options"]["generation"]["temperature"], 0.8)
        self.assertEqual(capture["options"]["max_tokens"], 1024)
        self.assertEqual(result["result"]["evidence"], [])
        payload["system_prompt"] = "Changed immediately"
        payload["messages"].extend([{"role": "assistant", "content": "Earlier answer"},
                                    {"role": "user", "content": "Follow-up"}])
        self.assertEqual(self.wait(self.app.start(payload))["status"], "complete")
        capture = self.capture()
        self.assertEqual(capture["messages"][0]["content"], "Changed immediately")
        self.assertEqual(capture["messages"][-2]["content"], "Earlier answer")
        self.assertEqual(capture["messages"][-1]["content"], "Follow-up")
        self.assertEqual(self.wait(self.app.start(self.payload("New conversation")))["status"], "complete")
        self.assertEqual(len(self.capture()["messages"]), 2)

    def test_grounded_profiles_and_explicit_resources(self):
        Profiles(self.root).save("reader", ["corpus", "dict", "missing"], False)
        payload = self.payload("Consider this", "grounded")
        payload.update(profile="reader", edition="edition", citation="327a", headword="καταβαίνω")
        result = self.wait(self.app.start(payload))
        self.assertEqual(result["status"], "complete")
        evidence = result["result"]["evidence"]
        self.assertEqual([e["record"]["provider"] for e in evidence], ["corpus", "dict"])
        self.assertTrue(any("missing: not installed" in w for w in result["result"]["warnings"]))
        capture = self.capture()
        self.assertIn("κατέβην", capture["messages"][-1]["content"])
        self.assertIn("scholarly_classification", capture["messages"][-1]["content"])
        Profiles(self.root).save("text", ["corpus", "dict"], True)
        payload["profile"] = "text"
        result = self.wait(self.app.start(payload))["result"]
        self.assertEqual([e["record"]["provider"] for e in result["evidence"]], ["corpus"])
        payload["include"] = ["corpus", "dict"]
        result = self.wait(self.app.start(payload))["result"]
        self.assertEqual([e["record"]["provider"] for e in result["evidence"]], ["corpus", "dict"])
        Registry(self.root).set_enabled("dict", False)
        result = self.wait(self.app.start(payload))["result"]
        self.assertEqual([e["record"]["provider"] for e in result["evidence"]], ["corpus"])
        self.assertFalse(any("disabled" in w for w in result["warnings"]))
        self.assertIn("disabled", [s["reason"] for s in result["selections"]["lookup"]])

    def test_stop_cancels_generation(self):
        job_id = self.app.start(self.payload("WAIT"))
        deadline = time.monotonic() + 5
        while not (self.root / "capture.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue((self.root / "capture.json").exists())
        self.assertEqual(self.app.stop(job_id), "cancelled")
        self.assertEqual(self.wait(job_id)["status"], "cancelled")


    def test_invalid_inputs_are_explicit(self):
        payload = self.payload()
        payload["temperature"] = float("nan")
        with self.assertRaises(ValueError):
            self.app.start(payload)
        payload["temperature"] = 0.5
        payload["messages"] = [{"role": "system", "content": "injected"}]
        with self.assertRaises(ValueError):
            self.app.start(payload)

    def test_http_local_host_origin_and_static_page(self):
        server = Server(("127.0.0.1", 0), self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request("GET", "/")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b"What would you like to look up?", response.read())
            conn.request("GET", "/conversation")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b"PlatoSI Playground", response.read())
            conn.request("GET", "/api/lookups")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            capabilities = json.loads(response.read())["capabilities"]
            self.assertTrue(any(item["operation"] == "word.analyze" for item in capabilities))
            conn.request("GET", "/api/bootstrap", headers={"Host": "attacker.example"})
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            body = json.dumps(self.payload()).encode("utf-8")
            conn.request("POST", "/api/jobs", body=body,
                         headers={"Content-Type": "application/json", "Origin": "http://attacker.example"})
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            origin = f"http://127.0.0.1:{server.server_port}"
            lookup = json.dumps({"operation": "word.analyze", "payload": {"form": "κατέβην"}}).encode("utf-8")
            conn.request("POST", "/api/lookup", body=lookup,
                         headers={"Content-Type": "application/json", "Origin": origin})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["entries"]["records"][0]["headword"], "κατέβην")
            conn.request("POST", "/api/jobs", body=body,
                         headers={"Content-Type": "application/json", "Origin": origin})
            response = conn.getresponse()
            self.assertEqual(response.status, 202)
            job_id = json.loads(response.read())["id"]
            self.assertEqual(self.wait(job_id)["status"], "complete")
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_lan_authentication_and_origin(self):
        server = Server(("0.0.0.0", 0), self.app, lan=True,
                        addresses=["192.168.1.25"], access_token="test-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host = f"192.168.1.25:{server.server_port}"
            origin = f"http://{host}"
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)

            def request(method, path, body=None, headers=None):
                conn.request(method, path, body, {"Host": host, **(headers or {})})
                response = conn.getresponse()
                data = response.read()
                return response, data

            response, data = request("GET", "/")
            self.assertEqual(response.status, 200)
            self.assertIn(b"Enter the access token", data)
            self.assertNotIn(b"test-token", data)
            self.assertEqual(request("GET", "/api/bootstrap")[0].status, 401)
            self.assertEqual(request("GET", "/app.js")[0].status, 401)
            self.assertEqual(request("GET", "/reader")[0].status, 401)
            self.assertEqual(request("GET", "/reader.js")[0].status, 401)
            self.assertEqual(request("GET", "/lookup.js")[0].status, 401)
            self.assertEqual(request("GET", "/api/lookups")[0].status, 401)
            self.assertEqual(request("GET", "/api/reader/options")[0].status, 401)
            form = urlencode({"token": "test-token"})
            form_headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": origin}
            self.assertEqual(request("POST", "/login", form,
                                     {**form_headers, "Origin": "http://attacker.example"})[0].status, 403)
            self.assertEqual(request("POST", "/login", urlencode({"token": "wrong"}), form_headers)[0].status, 403)
            response, _ = request("POST", "/login", form, form_headers)
            self.assertEqual(response.status, 303)
            cookie = response.getheader("Set-Cookie")
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=Strict", cookie)
            cookie_header = cookie.split(";", 1)[0]
            response, data = request("GET", "/", headers={"Cookie": cookie_header})
            self.assertEqual(response.status, 200)
            self.assertIn(b"What would you like to look up?", data)
            response, data = request("GET", "/conversation", headers={"Cookie": cookie_header})
            self.assertEqual(response.status, 200)
            self.assertIn(b"Experimental, local conversation", data)
            self.assertEqual(request("GET", "/api/bootstrap", headers={"Cookie": cookie_header})[0].status, 200)
            self.assertEqual(request("GET", "/reader", headers={"Cookie": cookie_header})[0].status, 200)
            self.assertEqual(request("GET", "/api/reader/options", headers={"Cookie": cookie_header})[0].status, 200)
            body = json.dumps(self.payload()).encode("utf-8")
            headers = {"Content-Type": "application/json", "Origin": origin, "Cookie": cookie_header}
            self.assertEqual(request("POST", "/api/jobs", body,
                                     {**headers, "Origin": "http://attacker.example"})[0].status, 403)
            response, data = request("POST", "/api/jobs", body, headers)
            self.assertEqual(response.status, 202)
            job_id = json.loads(data)["id"]
            self.assertEqual(self.wait(job_id)["status"], "complete")
            self.assertEqual(request("GET", "/api/jobs/" + job_id)[0].status, 401)
            self.assertEqual(request("GET", "/api/jobs/" + job_id,
                                     headers={"Cookie": cookie_header})[0].status, 200)
            conn.request("GET", "/", headers={"Host": f"attacker.example:{server.server_port}"})
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_only_private_ipv4_clients_are_allowed_for_lan(self):
        for address in ("192.168.1.2", "10.1.2.3", "172.16.0.1", "172.31.255.254"):
            self.assertTrue(private_ipv4(address))
        for address in ("8.8.8.8", "172.32.0.1", "169.254.1.1", "127.0.0.1", "::1", "invalid"):
            self.assertFalse(private_ipv4(address))
        with self.assertRaises(ValueError):
            Server(("0.0.0.0", 0), self.app)
        with self.assertRaises(ValueError):
            Server(("0.0.0.0", 0), self.app, lan=True, addresses=["8.8.8.8"])
        with patch("platosi.playground.lan_addresses", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "No private IPv4 address"):
                serve(self.root, 0, lan=True)

    def test_listener_on_this_computers_lan_address(self):
        addresses = lan_addresses()
        if not addresses:
            self.skipTest("No private IPv4 address detected on this computer")
        server = Server(("0.0.0.0", 0), self.app, lan=True,
                        addresses=addresses, access_token="test-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(server.server_address[0], "0.0.0.0")
            host = f"{addresses[0]}:{server.server_port}"
            conn = http.client.HTTPConnection(addresses[0], server.server_port, timeout=5)
            conn.request("GET", "/")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b"Enter the access token", response.read())
            form = urlencode({"token": "test-token"})
            conn.request("POST", "/login", form, {
                "Content-Type": "application/x-www-form-urlencoded", "Origin": "http://" + host
            })
            response = conn.getresponse()
            self.assertEqual(response.status, 303)
            cookie = response.getheader("Set-Cookie").split(";", 1)[0]
            response.read()
            conn.request("GET", "/api/bootstrap", headers={"Cookie": cookie})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("mock", [p["id"] for p in json.loads(response.read())["models"]])
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
