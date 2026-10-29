"""Local-only Ollama adapter; no other provider depends on Ollama."""

import http.client
import json
from urllib.parse import urlsplit


class OllamaProvider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.config = manifest["config"]
        endpoint = urlsplit(self.config["endpoint"])
        if (endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "localhost", "::1")
                or endpoint.username or endpoint.password or endpoint.path not in ("", "/")
                or endpoint.query or endpoint.fragment):
            raise ValueError("Ollama endpoint must be a local HTTP loopback origin")
        self.host = endpoint.hostname
        self.port = endpoint.port or 11434
        self.timeout = self.config.get("timeout_seconds", 300)
        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("Ollama timeout_seconds must be positive")

    def request(self, method, path, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        timeout = min(self.timeout, 5) if method == "GET" else self.timeout
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read()
            if response.status != 200:
                raise RuntimeError(f"Ollama {path} returned HTTP {response.status}: {raw.decode('utf-8', 'replace')}")
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"Ollama {path} returned a non-object response")
            return data
        finally:
            connection.close()

    def available(self):
        try:
            self.list_models()
            return True
        except OSError:
            return False

    def list_models(self):
        data = self.request("GET", "/api/tags")
        models = data.get("models")
        if not isinstance(models, list):
            raise ValueError("Ollama returned an invalid models list")
        result = []
        for item in models:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError("Ollama returned an invalid model record")
            if item.get("remote_host") or item.get("remote_model") or item["name"].endswith(":cloud"):
                continue
            result.append({"name": item["name"], "details": item.get("details", {}),
                           "digest": item.get("digest")})
        return result

    def generate(self, prompt, options):
        model = options.get("model") or self.config.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Select a model via --model or the Ollama provider configuration")
        models = self.list_models()
        names = [entry["name"] for entry in models]
        if model not in names:
            raise ValueError(f"Local model {model!r} is not available; discovered: {', '.join(names) or '(none)'}")
        generation = options.get("generation", {})
        if not isinstance(generation, dict):
            raise ValueError("Generation options must be a JSON object")
        payload = {"model": model, "prompt": prompt, "stream": False,
                   "think": self.config.get("think", False),
                   "options": {**self.config.get("generation", {}), **generation}}
        data = self.request("POST", "/api/generate", payload)
        if not isinstance(data.get("response"), str) or not data["response"].strip():
            raise ValueError("Ollama returned an empty or invalid response")
        return {"text": data["response"], "model": data.get("model", model),
                "done_reason": data.get("done_reason")}


def create_provider(manifest, root):
    return OllamaProvider(manifest, root)
