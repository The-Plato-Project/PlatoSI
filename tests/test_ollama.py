import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main()
