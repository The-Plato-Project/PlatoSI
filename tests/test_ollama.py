import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.cancellation import Cancellation, Cancelled
path = ROOT / "plugins" / "ollama" / "provider.py"
spec = importlib.util.spec_from_file_location("test_ollama_provider", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OllamaTests(unittest.TestCase):
    def setUp(self):
        manifest_path = ROOT / "plugins" / "ollama" / "plugin.json"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.provider = module.create_provider(self.manifest, ROOT)

    def test_only_local_http_endpoints_are_allowed(self):
        for endpoint in ("https://localhost:11434", "http://example.com:11434",
                         "http://127.0.0.1.evil:11434", "http://localhost:11434/api",
                         "http://user:pass@localhost:11434"):
            with self.subTest(endpoint=endpoint):
                self.manifest["config"]["endpoint"] = endpoint
                with self.assertRaises(ValueError):
                    module.create_provider(self.manifest, ROOT)

    def test_discovery_and_generation_use_local_models(self):
        calls = []

        def request(method, path, payload=None):
            calls.append((method, path, payload))
            if path == "/api/tags":
                return {"models": [{"name": "local:9b", "digest": "abc"},
                                   {"name": "remote:cloud"},
                                   {"name": "proxy", "remote_host": "example.com"}]}
            return {"response": "Text [E1]", "model": payload["model"], "done_reason": "stop"}

        with patch.object(self.provider, "request", side_effect=request):
            self.assertEqual([m["name"] for m in self.provider.list_models()], ["local:9b"])
            result = self.provider.generate("evidence", {"model": "local:9b",
                                                         "generation": {"temperature": 0.1}})
            self.assertEqual(result["text"], "Text [E1]")
            payload = calls[-1][2]
            self.assertEqual((calls[-1][0], calls[-1][1]), ("POST", "/api/generate"))
            self.assertFalse(payload["stream"])
            self.assertFalse(payload["think"])
            self.assertEqual(payload["options"]["temperature"], 0.1)
            self.assertEqual(payload["options"]["num_predict"], 500)
            with self.assertRaisesRegex(ValueError, "not available"):
                self.provider.generate("evidence", {"model": "remote:cloud"})
            with self.assertRaisesRegex(ValueError, "not available"):
                self.provider.generate("evidence", {"model": "missing"})
            self.assertTrue(all(path in ("/api/tags", "/api/generate") for _, path, _ in calls))

    def test_unavailable_and_invalid_responses_are_explicit(self):
        with patch.object(self.provider, "request", side_effect=ConnectionRefusedError("offline")):
            self.assertFalse(self.provider.available())
        with patch.object(self.provider, "request", return_value={"models": "invalid"}):
            with self.assertRaisesRegex(ValueError, "invalid models list"):
                self.provider.available()
        with patch.object(self.provider, "request", side_effect=[
                {"models": [{"name": "local:9b"}]}, {"response": ""}]):
            with self.assertRaisesRegex(ValueError, "empty or invalid response"):
                self.provider.generate("evidence", {"model": "local:9b"})

    def test_chat_cancellation_interrupts_stream(self):
        started = threading.Event()
        release = threading.Event()

        class FakeOllama(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                self.wfile.write(b'{"message":{"content":"partial"},"done":false}\n')
                self.wfile.flush()
                started.set()
                release.wait(5)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.manifest["config"]["endpoint"] = f"http://127.0.0.1:{server.server_port}"
        provider = module.create_provider(self.manifest, ROOT)
        token = Cancellation()
        result = []

        def run():
            try:
                provider.chat([{"role": "user", "content": "test"}], {"model": "local"}, token)
            except Exception as error:
                result.append(error)

        try:
            with patch.object(provider, "list_models", return_value=[{"name": "local"}]):
                thread = threading.Thread(target=run, daemon=True)
                thread.start()
                self.assertTrue(started.wait(5))
                token.cancel()
                thread.join(3)
                self.assertFalse(thread.is_alive(), "Cancelling did not interrupt the HTTP stream")
                self.assertIsInstance(result[0], Cancelled)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            server_thread.join()

    def test_chat_reads_split_chunked_unicode_and_applies_token_limit(self):
        requests = []

        class FakeOllama(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                records = [
                    {"message": {"content": "κατέβην "}, "done": False},
                    {"message": {"content": "χθὲς"}, "done": True, "model": "local", "done_reason": "stop"},
                ]
                body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8")
                for start in range(0, len(body), 5):
                    chunk = body[start:start + 5]
                    self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.manifest["config"]["endpoint"] = f"http://127.0.0.1:{server.server_port}"
            provider = module.create_provider(self.manifest, ROOT)
            with patch.object(provider, "list_models", return_value=[{"name": "local"}]):
                response = provider.chat([{"role": "system", "content": "visible prompt"},
                                          {"role": "user", "content": "test"}],
                                         {"model": "local", "max_tokens": 123}, Cancellation())
            self.assertEqual(response["text"], "κατέβην χθὲς")
            self.assertEqual(requests[0]["messages"][0]["content"], "visible prompt")
            self.assertEqual(requests[0]["options"]["num_predict"], 123)
            self.assertNotIn("format", requests[0])
            schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
            with patch.object(provider, "list_models", return_value=[{"name": "local"}]):
                provider.chat([{"role": "user", "content": "test"}],
                              {"model": "local", "response_format": "json", "response_schema": schema},
                              Cancellation())
            self.assertEqual(requests[1]["format"], schema)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
